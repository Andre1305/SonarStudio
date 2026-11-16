"""Testes da 4.10-Mapa-test.1: estilo da batimetria, mapa de fundo e integração."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
import numpy as np


class BathyStyleTests(unittest.TestCase):
    def test_hillshade_flat_is_sin_altitude(self):
        from bathy_style import hillshade
        s = hillshade(np.full((8, 8), 10.), 2.)
        np.testing.assert_allclose(s, np.sin(np.radians(45)), atol=1e-6)

    def test_hillshade_inclined_plane_constant_and_nan_preserved(self):
        from bathy_style import hillshade
        d = np.tile(np.arange(10.), (10, 1))
        d[3, 3] = np.nan
        s = hillshade(d, 1.)
        self.assertTrue(np.isnan(s[3, 3]))
        far = s[6:, 6:]
        self.assertLess(np.ptp(far), 1e-6)
        f = s[np.isfinite(s)]
        self.assertTrue(((f >= 0) & (f <= 1)).all())

    def test_hillshade_tiny_and_all_nan(self):
        from bathy_style import hillshade, compose
        self.assertEqual(hillshade(np.array([[5.]]), 1.).shape, (1, 1))
        self.assertTrue(np.isnan(hillshade(np.full((4, 4), np.nan), 1.)).all())
        empty = np.full((4, 4), np.nan)
        rgba = compose(empty, 0, 10, 'Blues', shade=hillshade(empty, 1.))
        self.assertEqual(rgba[..., 3].max(), 0)

    def test_banded_steps(self):
        from bathy_style import banded
        np.testing.assert_allclose(banded(np.array([0., .9, 1., 2.5, 10.]), 0, 10, 1.), [0, 0, .1, .2, 1.])
        self.assertTrue(np.isnan(banded(np.array([np.nan]), 0, 10, 1.))[0])

    def test_compose_opacity_and_shade(self):
        from bathy_style import compose
        d = np.array([[1., np.nan]])
        a = compose(d, 0, 10, 'Blues', opacity=.5)
        self.assertEqual(a.dtype, np.uint8)
        self.assertEqual(a[0, 0, 3], 128)
        self.assertEqual(a[0, 1, 3], 0)
        dark = compose(d, 0, 10, 'Blues', shade=np.zeros_like(d))
        self.assertTrue((dark[0, 0, :3] <= a[0, 0, :3]).all())
        self.assertTrue((dark[0, 0, :3] < a[0, 0, :3]).any())

    def test_chaikin_open_keeps_ends_and_closed_stays_closed(self):
        from bathy_style import chaikin
        p = np.array([[0, 0], [10, 0], [10, 10.]])
        c = chaikin(p)
        np.testing.assert_array_equal(c[0], p[0])
        np.testing.assert_array_equal(c[-1], p[-1])
        self.assertGreater(len(c), len(p))
        r = np.array([[0, 0], [10, 0], [10, 10], [0, 0.]])
        cr = chaikin(r)
        np.testing.assert_array_equal(cr[0], cr[-1])
        self.assertGreater(len(cr), len(r))
        np.testing.assert_array_equal(chaikin(p[:2]), p[:2])

    def test_label_positions_spacing_and_upright(self):
        from bathy_style import label_positions
        line = np.c_[np.linspace(500, 0, 51), np.zeros(51)]
        labels = label_positions(line, spacing_px=200)
        self.assertEqual(len(labels), 3)
        self.assertAlmostEqual(labels[0][0], 400, delta=1)
        self.assertTrue(all(-90 < a <= 90 for _, _, a in labels))
        self.assertEqual(label_positions(np.array([[0, 0], [50, 0.]])), [])


def solid_png(rgb=(255, 0, 0), size=256):
    from rasterio.io import MemoryFile
    data = np.zeros((3, size, size), np.uint8)
    for i, v in enumerate(rgb):
        data[i] = v
    import warnings
    warnings.simplefilter('ignore', UserWarning)
    with MemoryFile() as memory:
        with memory.open(driver='PNG', width=size, height=size, count=3, dtype='uint8') as ds:
            ds.write(data)
        return memory.read()


class FakeFetch:
    def __init__(self, payload=None, error=None):
        self.payload = payload if payload is not None else solid_png()
        self.error = error
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        if self.error:
            raise self.error
        return self.payload


class Clock:
    def __init__(self):
        self.now = 1_000_000.

    def __call__(self):
        return self.now


class BasemapTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from unittest.mock import patch
        import basemap
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        guard = patch.object(basemap, 'http_fetch', side_effect=AssertionError('rede acessada no teste'))
        guard.start()
        self.addCleanup(guard.stop)

    def cache(self, fetch, url=None, clock=None):
        from pathlib import Path
        from basemap import TileCache, DEFAULT_URL
        return TileCache(Path(self.tmp.name), url or DEFAULT_URL, fetch=fetch, clock=clock or Clock())

    def test_tile_math_known_values(self):
        from basemap import lonlat_to_tile, tile_bounds_3857
        self.assertEqual(tuple(int(v) for v in lonlat_to_tile(0, 0, 1)), (1, 1))
        x, y = lonlat_to_tile(-46.6333, -23.5505, 10)
        self.assertEqual((int(x), int(y)), (379, 580))
        left, bottom, right, top = tile_bounds_3857(0, 0, 0)
        self.assertAlmostEqual(right, 20037508.34, places=1)
        self.assertAlmostEqual(bottom, -20037508.34, places=1)
        self.assertAlmostEqual(left, -right, places=3)

    def test_latitude_clamped(self):
        from basemap import lonlat_to_tile, MAX_LAT
        self.assertEqual(lonlat_to_tile(0, 89.9, 3), lonlat_to_tile(0, MAX_LAT, 3))
        self.assertEqual(lonlat_to_tile(0, -90, 3), lonlat_to_tile(0, -MAX_LAT, 3))

    def test_zoom_for_resolution(self):
        from basemap import zoom_for_resolution
        self.assertEqual(zoom_for_resolution(1., 0), 18)
        self.assertEqual(zoom_for_resolution(.01, 0), 19)
        self.assertEqual(zoom_for_resolution(1e6, 0), 0)
        self.assertEqual(zoom_for_resolution(.01, 0, max_zoom=17), 17)

    def test_config_rejects_bad_url(self):
        from basemap import BasemapConfig
        for url in ['http://a/{z}/{x}/{y}.png', 'https://a/{z}/{x}.png', 'ftp://{z}{x}{y}']:
            with self.assertRaises(ValueError):
                BasemapConfig(url=url).validate()
        with self.assertRaises(ValueError):
            BasemapConfig(max_zoom=30).validate()
        BasemapConfig().validate()
        self.assertFalse(BasemapConfig().enabled)
        restored = BasemapConfig.from_state({'max_zoom': 17, 'x': 1})
        self.assertEqual(restored.max_zoom, 17)
        self.assertEqual(BasemapConfig.from_state(BasemapConfig(enabled=True).state()).enabled, True)

    def test_cache_hit_expiry_and_url_isolation(self):
        fetch, clock = FakeFetch(), Clock()
        cache = self.cache(fetch, clock=clock)
        tile = cache.get(3, 2, 1)
        self.assertEqual(tile.shape, (256, 256, 4))
        self.assertEqual(tuple(tile[0, 0]), (255, 0, 0, 255))
        cache.get(3, 2, 1)
        self.assertEqual(len(fetch.calls), 1)
        self.assertIn('/3/2/1', fetch.calls[0])
        clock.now += 8 * 86400
        cache.get(3, 2, 1)
        self.assertEqual(len(fetch.calls), 2)
        other = FakeFetch()
        self.cache(other, url='https://example.org/{z}/{x}/{y}.png').get(3, 2, 1)
        self.assertEqual(len(other.calls), 1)

    def test_fetch_failure_returns_none_and_backs_off(self):
        fetch, clock = FakeFetch(error=OSError('offline')), Clock()
        cache = self.cache(fetch, clock=clock)
        self.assertIsNone(cache.get(1, 0, 0))
        self.assertIsNone(cache.get(1, 0, 0))
        self.assertEqual(len(fetch.calls), 1)
        clock.now += 61
        cache.get(1, 0, 0)
        self.assertEqual(len(fetch.calls), 2)

    def test_corrupt_cached_tile_refetched(self):
        fetch = FakeFetch()
        cache = self.cache(fetch)
        path = cache.tile_path(2, 1, 1)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'lixo')
        tile = cache.get(2, 1, 1)
        self.assertEqual(len(fetch.calls), 1)
        self.assertEqual(tile.shape, (256, 256, 4))
        bad = self.cache(FakeFetch(payload=b'nao e imagem'))
        self.assertIsNone(bad.get(2, 0, 0))

    def test_cache_root_fallback(self):
        from pathlib import Path
        from unittest.mock import patch
        from basemap import cache_root
        blocker = Path(self.tmp.name) / 'arquivo'
        blocker.write_text('x')
        home = Path(self.tmp.name) / 'home'
        with patch('pathlib.Path.home', return_value=home):
            root = cache_root({'LOCALAPPDATA': str(blocker)})
        self.assertTrue(str(root).startswith(str(home)))
        good = cache_root({'LOCALAPPDATA': str(Path(self.tmp.name) / 'local')})
        self.assertEqual(good, Path(self.tmp.name) / 'local' / 'SonarStudio' / 'tiles')

    def test_tile_count_capped_by_lowering_zoom(self):
        from rasterio.crs import CRS
        from basemap import tiles_for_view, MAX_TILES_PER_VIEW
        crs = CRS.from_epsg(31983)
        bounds = (300000., 7380000., 350000., 7430000.)
        z, tiles = tiles_for_view(bounds, crs, .1, 19)
        self.assertLessEqual(len(tiles), MAX_TILES_PER_VIEW)
        self.assertGreater(len(tiles), 0)
        self.assertLess(z, 19)

    def test_render_view_reprojects_solid_tiles(self):
        from rasterio.crs import CRS
        from basemap import render_view
        cache = self.cache(FakeFetch())
        bounds = (330000., 7394000., 330400., 7394200.)
        image = render_view(cache, bounds, CRS.from_epsg(31983), 200, 100, 2., 19)
        self.assertEqual(image.shape, (100, 200, 4))
        self.assertEqual(tuple(image[50, 100]), (255, 0, 0, 255))

    def test_render_view_none_when_all_fail(self):
        from rasterio.crs import CRS
        from basemap import render_view
        cache = self.cache(FakeFetch(error=OSError('offline')))
        self.assertIsNone(render_view(cache, (330000., 7394000., 330400., 7394200.), CRS.from_epsg(31983), 200, 100, 2., 19))
        ok = self.cache(FakeFetch())
        self.assertIsNone(render_view(ok, (330000., 7394000., 330400., 7394200.), CRS.from_epsg(31983), 200, 100, 2., 19, cancel=lambda: True))


class StubLoader:
    def __init__(self):
        self.requests = []

    def request(self, *args):
        self.requests.append(args)

    def shutdown(self):
        pass


class MapIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self):
        import tempfile
        from unittest.mock import patch
        import basemap
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        guard = patch.object(basemap, 'http_fetch', side_effect=AssertionError('rede acessada no teste'))
        guard.start()
        self.addCleanup(guard.stop)

    def depth_tif(self):
        import rasterio
        from rasterio.transform import from_origin
        from pathlib import Path
        path = Path(self.tmp.name) / 'prof.tif'
        data = np.tile(np.linspace(2, 12, 200, dtype='float32'), (100, 1))
        with rasterio.open(path, 'w', driver='GTiff', width=200, height=100, count=1, dtype='float32', crs='EPSG:31983',
                           transform=from_origin(330000, 7394200, 2, 2), nodata=-9999.) as ds:
            ds.write(data, 1)
        return path

    def mapview(self):
        from app import MapView
        view = MapView()
        view.resize(200, 100)
        view.loader = StubLoader()
        self.addCleanup(lambda: view.dataset and view.dataset.close())
        return view

    def pixel(self, image, x, y):
        color = image.pixelColor(x, y)
        return color.red(), color.green(), color.blue()

    def test_loader_drops_stale_results(self):
        import time
        from rasterio.crs import CRS
        from basemap import BasemapConfig
        from basemap_worker import BasemapLoader
        red = np.zeros((256, 256, 4), np.uint8)
        red[..., 0] = red[..., 3] = 255

        class SlowCache:
            def get(self, z, x, y):
                time.sleep(.05)
                return red

        loader = BasemapLoader(lambda url: SlowCache())
        self.addCleanup(loader.shutdown)
        got = []
        loader.ready.connect(lambda key, image: got.append(key))
        crs, config = CRS.from_epsg(31983), BasemapConfig(enabled=True)
        bounds = (330000., 7394000., 330400., 7394200.)
        loader.request('k1', bounds, crs, 200, 100, 2., config)
        loader.request('k2', bounds, crs, 200, 100, 2., config)
        deadline = time.time() + 5
        while not got and time.time() < deadline:
            self.qt.processEvents()
            time.sleep(.01)
        time.sleep(.3)
        self.qt.processEvents()
        self.assertEqual(got, ['k2'])

    def test_mapview_draws_basemap_under_bathymetry(self):
        from PySide6.QtGui import QImage, QColor
        view = self.mapview()
        view.depth_palette = 'Blues'
        view.relief_visible = False
        view.open_raster(str(self.depth_tif()))
        view.render_raster()
        size = (view.width(), view.height())
        cx, cy = size[0] // 2, size[1] // 2
        alone = self.pixel(view.grab().toImage(), cx, cy)
        view.basemap_config.enabled = True
        red = QImage(*size, QImage.Format.Format_RGBA8888)
        red.fill(QColor(255, 0, 0))
        view.on_basemap(view.basemap_view_key(), red)
        view.layer_opacity = .5
        view.render_raster()
        image = view.grab().toImage()
        mixed = self.pixel(image, cx, cy)
        expected = (.5 * alone[0] + 127.5, .5 * alone[1], .5 * alone[2])
        for got, want in zip(mixed, expected):
            self.assertAlmostEqual(got, want, delta=6)
        self.assertEqual(self.pixel(image, 2, cy), (255, 0, 0))

    def test_basemap_off_by_default_no_request(self):
        view = self.mapview()
        self.assertFalse(view.basemap_config.enabled)
        view.open_raster(str(self.depth_tif()))
        view.render_raster()
        self.assertEqual(view.loader.requests, [])
        view.basemap_config.enabled = True
        view.render_raster()
        self.assertEqual(len(view.loader.requests), 1)
        view.render_raster()
        self.assertEqual(len(view.loader.requests), 1)

    def test_contours_loaded_smoothed(self):
        view = self.mapview()
        line = np.array([[330000., 7394000.], [330200., 7394000.], [330200., 7394200.]])
        view.set_contours([(5., line)])
        depth, points = view.contours[0]
        self.assertEqual(depth, 5.)
        self.assertGreater(len(points), len(line))
        np.testing.assert_array_equal(points[0], line[0])
        np.testing.assert_array_equal(points[-1], line[-1])
        view.open_raster(str(self.depth_tif()))
        view.contours_visible = True
        view.contour_interval = 1.
        self.assertFalse(view.grab().toImage().isNull())


class ReviewFixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self):
        import tempfile
        from unittest.mock import patch
        import basemap
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        guard = patch.object(basemap, 'http_fetch', side_effect=AssertionError('rede acessada no teste'))
        guard.start()
        self.addCleanup(guard.stop)

    def test_paletted_png_decodes_to_palette_colors(self):
        import warnings
        from rasterio.io import MemoryFile
        from basemap import decode_tile
        data = np.zeros((1, 256, 256), np.uint8)
        data[0, :, 128:] = 1
        warnings.simplefilter('ignore', UserWarning)
        with MemoryFile() as memory:
            with memory.open(driver='PNG', width=256, height=256, count=1, dtype='uint8') as ds:
                ds.write(data)
                ds.write_colormap(1, {0: (200, 10, 10, 255), 1: (10, 200, 10, 0)})
            payload = memory.read()
        tile = decode_tile(payload)
        self.assertEqual(tuple(tile[0, 0]), (200, 10, 10, 255))
        self.assertEqual(tuple(tile[0, 200]), (10, 200, 10, 0))

    def test_bands_align_with_isobaths_for_any_lo(self):
        from bathy_style import banded
        values = banded(np.array([1.9, 2.1, 2.9, 3.1]), 1.37, 10, 1.)
        self.assertNotEqual(values[0], values[1])
        self.assertEqual(values[1], values[2])
        self.assertNotEqual(values[2], values[3])
        self.assertTrue(((values >= 0) & (values <= 1)).all())

    def test_expired_tile_served_when_offline(self):
        from pathlib import Path
        from basemap import TileCache, DEFAULT_URL
        clock = Clock()
        online = FakeFetch()
        TileCache(Path(self.tmp.name), DEFAULT_URL, fetch=online, clock=clock).get(4, 1, 1)
        clock.now += 8 * 86400
        offline = FakeFetch(error=OSError('offline'))
        tile = TileCache(Path(self.tmp.name), DEFAULT_URL, fetch=offline, clock=clock).get(4, 1, 1)
        self.assertEqual(len(offline.calls), 1)
        self.assertEqual(tuple(tile[0, 0]), (255, 0, 0, 255))

    def test_disabling_cancels_running_job(self):
        import time
        from rasterio.crs import CRS
        from basemap import BasemapConfig
        from basemap_worker import BasemapLoader
        calls = []
        red = np.zeros((256, 256, 4), np.uint8)
        red[..., 0] = red[..., 3] = 255

        class SlowCache:
            def get(self, z, x, y):
                calls.append((z, x, y))
                time.sleep(.05)
                return red

        loader = BasemapLoader(lambda url: SlowCache())
        self.addCleanup(loader.shutdown)
        got = []
        loader.ready.connect(lambda key, image: got.append(key))
        loader.request('k', (300000., 7380000., 310000., 7390000.), CRS.from_epsg(31983), 800, 800, 1., BasemapConfig(enabled=True))
        time.sleep(.12)
        loader.cancel()
        seen = len(calls)
        time.sleep(.3)
        self.qt.processEvents()
        self.assertLessEqual(len(calls), seen + 1)
        self.assertEqual(got, [])

    def test_mapview_disable_calls_loader_cancel(self):
        from app import MapView
        view = MapView()

        class Loader(StubLoader):
            cancelled = 0

            def cancel(self):
                self.cancelled += 1

        view.loader = Loader()
        view.basemap_config.enabled = True
        view.set_basemap_enabled(False)
        self.assertEqual(view.loader.cancelled, 1)

    def test_opacity_applies_without_recompose(self):
        from PySide6.QtGui import QImage, QColor
        helper = MapIntegrationTests('test_mapview_draws_basemap_under_bathymetry')
        helper.tmp = self.tmp
        view = helper.mapview()
        helper.addCleanup = self.addCleanup
        view.depth_palette = 'Blues'
        view.relief_visible = False
        view.open_raster(str(helper.depth_tif()))
        view.basemap_config.enabled = True
        red = QImage(view.width(), view.height(), QImage.Format.Format_RGBA8888)
        red.fill(QColor(255, 0, 0))
        view.on_basemap(view.basemap_view_key(), red)
        view.layer_opacity = .5
        view.render_raster()
        cx, cy = view.width() // 2, view.height() // 2
        half = helper.pixel(view.grab().toImage(), cx, cy)
        view.layer_opacity = .2
        view.update()
        faint = helper.pixel(view.grab().toImage(), cx, cy)
        self.assertGreater(faint[0], half[0] + 20)


if __name__ == '__main__':
    unittest.main()
