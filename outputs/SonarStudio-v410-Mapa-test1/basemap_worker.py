"""Carregamento do mapa de fundo fora da thread da interface; só o pedido mais recente é entregue."""
import threading
import numpy as np
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage


class BasemapLoader(QObject):
    ready = Signal(object, QImage)

    def __init__(self, cache_factory):
        super().__init__()
        self.cache_factory = cache_factory
        self.caches = {}
        self.condition = threading.Condition()
        self.pending = None
        self.latest = None
        self.stopped = False
        self.thread = threading.Thread(target=self._run, name='basemap-loader', daemon=True)
        self.thread.start()

    def request(self, key, bounds, crs, width, height, m_per_px, config):
        with self.condition:
            self.latest = key
            self.pending = (key, tuple(bounds), crs, int(width), int(height), float(m_per_px), config)
            self.condition.notify()

    def shutdown(self):
        with self.condition:
            self.stopped = True
            self.latest = None
            self.condition.notify()
        self.thread.join(2)

    def _cache(self, url):
        if url not in self.caches:
            self.caches[url] = self.cache_factory(url)
        return self.caches[url]

    def _run(self):
        from basemap import render_view
        while True:
            with self.condition:
                while self.pending is None and not self.stopped:
                    self.condition.wait()
                if self.stopped:
                    return
                job, self.pending = self.pending, None
            key, bounds, crs, width, height, m_per_px, config = job
            stale = lambda: self.stopped or self.latest != key
            try:
                rgba = render_view(self._cache(config.url), bounds, crs, width, height, m_per_px, int(config.max_zoom), cancel=stale)
            except Exception:
                rgba = None
            if rgba is None or stale():
                continue
            rgba = np.ascontiguousarray(rgba)
            image = QImage(rgba.data, rgba.shape[1], rgba.shape[0], rgba.strides[0], QImage.Format.Format_RGBA8888).copy()
            if not stale():
                self.ready.emit(key, image)
