"""Mapa de fundo XYZ (Web Mercator): matemática de tiles, cache em disco e reprojeção para a vista.

Opcional e desligado por padrão. Somente a área visível é baixada; sem pré-download em massa.
Falhas de rede nunca chegam à interface: retornam None.
"""
from dataclasses import dataclass, asdict, fields
from pathlib import Path
import hashlib
import math
import os
import threading
import time
import numpy as np

DEFAULT_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
DEFAULT_ATTRIBUTION = '© colaboradores do OpenStreetMap'
USER_AGENT = 'SonarStudio/4.10-Mapa-test.1'
MAX_TILES_PER_VIEW = 64
CACHE_DAYS = 7
FAIL_BACKOFF_S = 60
MAX_LAT = 85.05112878
TILE_SIZE = 256
EARTH_HALF = 20037508.342789244
_DOWNLOADS = threading.BoundedSemaphore(2)


def lonlat_to_tile(lon, lat, z):
    """Coordenadas fracionárias do tile XYZ que contém lon/lat no zoom z."""
    lat = max(-MAX_LAT, min(MAX_LAT, lat))
    n = 2 ** z
    x = (lon + 180.) / 360. * n
    rad = math.radians(lat)
    y = (1. - math.asinh(math.tan(rad)) / math.pi) / 2. * n
    return x, y


def tile_bounds_3857(x, y, z):
    """(left, bottom, right, top) do tile em metros EPSG:3857."""
    span = 2 * EARTH_HALF / 2 ** z
    left = -EARTH_HALF + x * span
    top = EARTH_HALF - y * span
    return left, top - span, left + span, top


def zoom_for_resolution(m_per_px, lat, max_zoom=19):
    """Menor zoom cuja resolução no solo é igual ou melhor que m_per_px."""
    lat = max(-MAX_LAT, min(MAX_LAT, lat))
    ground = 2 * math.pi * 6378137. * math.cos(math.radians(lat)) / TILE_SIZE
    for z in range(0, max_zoom + 1):
        if ground / 2 ** z <= m_per_px:
            return z
    return max_zoom


@dataclass
class BasemapConfig:
    url: str = DEFAULT_URL
    max_zoom: int = 19
    attribution: str = DEFAULT_ATTRIBUTION
    enabled: bool = False

    def validate(self):
        if not self.url.startswith('https://'):
            raise ValueError('A fonte do mapa precisa usar https://.')
        if not all(token in self.url for token in ['{z}', '{x}', '{y}']):
            raise ValueError('A URL do mapa precisa conter {z}, {x} e {y}.')
        if not 0 <= int(self.max_zoom) <= 22:
            raise ValueError('Zoom máximo deve ficar entre 0 e 22.')
        return self

    def state(self):
        return asdict(self)

    @classmethod
    def from_state(cls, data):
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (data or {}).items() if k in names})


def cache_root(env=os.environ):
    """Diretório do cache: LOCALAPPDATA/SonarStudio/tiles, ou ~/.sonarstudio/tiles se indisponível."""
    candidates = []
    if env.get('LOCALAPPDATA'):
        candidates.append(Path(env['LOCALAPPDATA']) / 'SonarStudio' / 'tiles')
    candidates.append(Path.home() / '.sonarstudio' / 'tiles')
    for root in candidates:
        try:
            root.mkdir(parents=True, exist_ok=True)
            probe = root / '.gravavel'
            probe.write_bytes(b'')
            probe.unlink()
            return root
        except OSError:
            continue
    return candidates[-1]


def http_fetch(url, timeout=10.):
    import urllib.request
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if getattr(response, 'status', 200) != 200:
            raise OSError(f'HTTP {response.status}')
        return response.read()


def decode_tile(payload):
    """Bytes PNG/JPEG → RGBA uint8 (H, W, 4), ou None se não for imagem."""
    from rasterio.io import MemoryFile
    from rasterio.errors import RasterioError
    import warnings
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            with MemoryFile(payload) as memory, memory.open() as ds:
                data = ds.read()
    except (RasterioError, ValueError, OSError):
        return None
    if data.dtype != np.uint8 or data.ndim != 3:
        return None
    if data.shape[0] in (1, 2):
        gray = data[0]
        alpha = data[1] if data.shape[0] == 2 else np.full_like(gray, 255)
        data = np.stack([gray, gray, gray, alpha])
    elif data.shape[0] == 3:
        data = np.concatenate([data, np.full_like(data[:1], 255)])
    return np.ascontiguousarray(np.moveaxis(data[:4], 0, -1))


class TileCache:
    def __init__(self, root, url, fetch=None, max_age_days=CACHE_DAYS, clock=time.time):
        self.url = url
        self.folder = Path(root) / hashlib.sha256(url.encode()).hexdigest()[:16]
        self.fetch = fetch
        self.max_age = max_age_days * 86400
        self.clock = clock
        self.failures = {}
        self.lock = threading.Lock()

    def tile_path(self, z, x, y):
        return self.folder / str(z) / str(x) / f'{y}.tile'

    def _download(self, z, x, y):
        fetch = self.fetch or http_fetch
        url = self.url.replace('{z}', str(z)).replace('{x}', str(x)).replace('{y}', str(y))
        with _DOWNLOADS:
            return fetch(url)

    def get(self, z, x, y):
        key = (z, x, y)
        path = self.tile_path(z, x, y)
        now = self.clock()
        try:
            if path.is_file() and now - path.stat().st_mtime <= self.max_age:
                tile = decode_tile(path.read_bytes())
                if tile is not None:
                    return tile
        except OSError:
            pass
        with self.lock:
            if self.failures.get(key, 0) > now:
                return None
        try:
            payload = self._download(z, x, y)
            tile = decode_tile(payload)
            if tile is None:
                raise ValueError('tile inválido')
        except Exception:
            with self.lock:
                self.failures[key] = now + FAIL_BACKOFF_S
            return None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix('.tmp')
            temporary.write_bytes(payload)
            os.utime(temporary, (now, now))
            temporary.replace(path)
        except OSError:
            pass
        return tile


def _tile_range(west, south, east, north, z):
    n = 2 ** z
    x0, y0 = lonlat_to_tile(west, north, z)
    x1, y1 = lonlat_to_tile(east, south, z)
    xs = range(max(0, int(x0)), min(n - 1, int(x1)) + 1)
    ys = range(max(0, int(y0)), min(n - 1, int(y1)) + 1)
    return xs, ys


def tiles_for_view(bounds, crs, m_per_px, max_zoom):
    """Zoom e tiles que cobrem a vista, reduzindo o zoom até caber em MAX_TILES_PER_VIEW."""
    from rasterio.warp import transform_bounds
    west, south, east, north = transform_bounds(crs, 'EPSG:4326', *bounds, densify_pts=21)
    z = zoom_for_resolution(m_per_px, (south + north) / 2, max_zoom)
    while True:
        xs, ys = _tile_range(west, south, east, north, z)
        if len(xs) * len(ys) <= MAX_TILES_PER_VIEW or z == 0:
            return z, [(x, y) for y in ys for x in xs]
        z -= 1


def render_view(cache, bounds, crs, width, height, m_per_px, max_zoom, cancel=lambda: False):
    """Imagem RGBA (height, width, 4) do mapa de fundo na vista, ou None se nada chegou."""
    from rasterio.transform import from_origin, from_bounds
    from rasterio.warp import reproject, Resampling
    if cancel():
        return None
    z, tiles = tiles_for_view(bounds, crs, m_per_px, max_zoom)
    if not tiles:
        return None
    xs = sorted({x for x, _ in tiles})
    ys = sorted({y for _, y in tiles})
    mosaic = np.zeros((4, len(ys) * TILE_SIZE, len(xs) * TILE_SIZE), np.uint8)
    received = False
    for x, y in tiles:
        if cancel():
            return None
        tile = cache.get(z, x, y)
        if tile is None or tile.shape[:2] != (TILE_SIZE, TILE_SIZE):
            continue
        row, col = (y - ys[0]) * TILE_SIZE, (x - xs[0]) * TILE_SIZE
        mosaic[:, row:row + TILE_SIZE, col:col + TILE_SIZE] = np.moveaxis(tile, -1, 0)
        received = True
    if not received or cancel():
        return None
    left, _, _, top = tile_bounds_3857(xs[0], ys[0], z)
    resolution = 2 * EARTH_HALF / 2 ** z / TILE_SIZE
    destination = np.zeros((4, height, width), np.uint8)
    reproject(mosaic, destination, src_transform=from_origin(left, top, resolution, resolution), src_crs='EPSG:3857',
              dst_transform=from_bounds(*bounds, width, height), dst_crs=crs, resampling=Resampling.bilinear)
    return np.ascontiguousarray(np.moveaxis(destination, 0, -1))
