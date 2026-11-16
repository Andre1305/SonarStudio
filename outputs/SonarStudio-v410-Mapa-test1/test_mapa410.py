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


if __name__ == '__main__':
    unittest.main()
