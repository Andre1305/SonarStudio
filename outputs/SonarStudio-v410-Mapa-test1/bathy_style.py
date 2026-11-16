"""Estilo de exibição da batimetria: relevo, faixas, composição RGBA e isóbatas suaves.

Somente visual; não altera a grade nem os arquivos exportados.
"""
import math
import numpy as np


def _derivative(a, axis, cell):
    """Derivada com diferenças centrais onde há vizinhos válidos e laterais nas bordas/buracos."""
    padded = np.pad(a, [(1, 1) if i == axis else (0, 0) for i in range(2)], constant_values=np.nan)
    take = lambda start: np.take(padded, range(start, start + a.shape[axis]), axis=axis)
    forward = take(2) - a
    backward = a - take(0)
    both = np.isfinite(forward) & np.isfinite(backward)
    result = np.where(both, (forward + backward) / 2, np.where(np.isfinite(forward), forward, backward))
    return np.nan_to_num(result, nan=0.) / cell


def hillshade(depth, cell, azimuth=315., altitude=45., z_factor=1.):
    """Relevo sombreado em [0,1]; profundidade positiva para baixo; NaN onde não há dado."""
    depth = np.asarray(depth, dtype=float)
    elevation = -depth
    dx = _derivative(elevation, 1, cell) * z_factor
    dy = -_derivative(elevation, 0, cell) * z_factor  # linhas crescem para o sul
    slope = np.arctan(np.hypot(dx, dy))
    aspect = np.arctan2(dy, -dx)
    zenith = math.radians(90. - altitude)
    sun = math.radians(360. - azimuth + 90.)
    shade = math.cos(zenith) * np.cos(slope) + math.sin(zenith) * np.sin(slope) * np.cos(sun - aspect)
    shade = np.clip(shade, 0, 1).astype(np.float32)
    shade[~np.isfinite(depth)] = np.nan
    return shade


def banded(depth, lo, hi, interval):
    """Normaliza a profundidade em [0,1], quantizada em faixas de `interval` metros."""
    depth = np.asarray(depth, dtype=float)
    span = max(float(hi) - float(lo), 1e-9)
    offset = depth - lo
    if interval and interval > 0:
        offset = np.floor(offset / interval + 1e-9) * interval
    return np.clip(offset / span, 0, 1)


def compose(depth, lo, hi, palette, *, interval=None, shade=None, opacity=1.):
    """RGBA uint8: paleta (em faixas ou contínua) × relevo, alfa = opacidade onde há dado."""
    from matplotlib import colormaps
    depth = np.asarray(depth, dtype=float)
    valid = np.isfinite(depth)
    x = banded(depth, lo, hi, interval or 0)
    rgba = colormaps[palette](np.where(valid, x, 0.))
    if shade is not None:
        factor = 0.5 + 0.5 * np.nan_to_num(np.asarray(shade, dtype=float), nan=1.)
        rgba[..., :3] *= factor[..., None]
    out = np.round(np.clip(rgba, 0, 1) * 255).astype(np.uint8)
    out[..., 3] = np.where(valid, round(255 * float(np.clip(opacity, 0, 1))), 0)
    return out


def chaikin(points, iterations=2):
    """Suavização de Chaikin; preserva pontas de linhas abertas e mantém anéis fechados."""
    points = np.asarray(points, dtype=float)
    if len(points) < 3:
        return points
    closed = np.array_equal(points[0], points[-1])
    for _ in range(max(0, int(iterations))):
        a, b = points[:-1], points[1:]
        q = .75 * a + .25 * b
        r = .25 * a + .75 * b
        inner = np.empty((2 * len(a), 2))
        inner[0::2], inner[1::2] = q, r
        points = np.vstack([inner, inner[:1]]) if closed else np.vstack([points[:1], inner, points[-1:]])
    return points


def label_positions(points, spacing_px=220., min_length_px=80.):
    """Posições (x, y, ângulo em graus) para rótulos ao longo de uma linha em pixels de tela."""
    points = np.asarray(points, dtype=float)
    if len(points) < 2:
        return []
    segments = np.diff(points, axis=0)
    lengths = np.hypot(segments[:, 0], segments[:, 1])
    cumulative = np.concatenate([[0.], np.cumsum(lengths)])
    total = cumulative[-1]
    if total < min_length_px or spacing_px <= 0:
        return []
    labels = []
    target = spacing_px / 2
    while target <= total + 1e-9:
        i = min(int(np.searchsorted(cumulative, target, side='right')) - 1, len(segments) - 1)
        while lengths[i] == 0 and i > 0:
            i -= 1
        t = (target - cumulative[i]) / max(lengths[i], 1e-12)
        x, y = points[i] + segments[i] * t
        angle = math.degrees(math.atan2(segments[i, 1], segments[i, 0]))
        if angle > 90:
            angle -= 180
        elif angle <= -90:
            angle += 180
        labels.append((float(x), float(y), angle))
        target += spacing_px
    return labels
