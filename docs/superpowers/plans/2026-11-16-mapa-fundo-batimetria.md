# Mapa de fundo e visual da batimetria — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adicionar ao SonarStudio um mapa de fundo XYZ (OpenStreetMap por padrão) e um visual de batimetria com relevo, faixas, transparência, isóbatas suavizadas/rotuladas e legenda, numa nova versão 4.10-Mapa-test.1.

**Architecture:** Dois módulos novos e testáveis sem GUI: `bathy_style.py`, com funções numpy puras de estilo, e `basemap.py`, com matemática de tiles, cache em disco e composição/reprojeção. Um terceiro módulo pequeno, `basemap_worker.py`, roda o carregamento numa thread Qt. `app.py` só troca a ordem de desenho do `MapView` e ganha controles novos. A grade e os arquivos de batimetria não mudam.

**Tech Stack:** Python 3.12, numpy, rasterio (`rasterio.warp.reproject`, `MemoryFile` para decodificar PNG/JPEG), matplotlib colormaps, PySide6. HTTP só com `urllib.request`.

**Spec:** `docs/superpowers/specs/2026-11-16-mapa-fundo-batimetria-design.md`

## Global Constraints

- Pasta da versão: `outputs/SonarStudio-v410-Mapa-test1`, versão `4.10-Mapa-test.1`, tag `sonarstudio-v4.10-Mapa-test.1`. A pasta da 4.9 não é alterada.
- Sem dependências novas. HTTP via `urllib.request`.
- O mapa de fundo começa **desligado**. Na primeira ativação aparece um aviso de privacidade que precisa ser aceito.
- User-Agent `SonarStudio/4.10-Mapa-test.1`, sem e-mail ou dado do usuário.
- URL padrão `https://tile.openstreetmap.org/{z}/{x}/{y}.png`, zoom máximo 19, atribuição `© colaboradores do OpenStreetMap` sempre visível quando o fundo é desenhado.
- Cache em `%LOCALAPPDATA%/SonarStudio/tiles/<sha256(url)[:16]>/z/x/y`. Se `LOCALAPPDATA` faltar ou não for gravável, usa `~/.sonarstudio/tiles/...`. Validade de 7 dias.
- No máximo 2 downloads simultâneos e no máximo 64 tiles por vista. Não há pré-download de área.
- Rede nunca trava a interface nem lança exceção para ela. Os testes não acessam a rede.
- Grade de profundidade, interpolação, GeoTIFF e GPKG ficam inalterados. A suavização das isóbatas é só no desenho.
- Textos da interface em português, no estilo do app existente.

## Review Focus

- **Sem internet ou servidor lento:** o mapa continua com o fundo liso, sem travar e sem repetir a requisição a cada repintura. Coberto em Task 3 (`test_fetch_failure_returns_none_and_backs_off`).
- **Pan/zoom rápido:** resultados de vistas antigas são descartados e o número de tiles fica limitado. Coberto em Task 3 (`test_tile_count_capped_by_lowering_zoom`) e Task 4 (`test_loader_drops_stale_results`).
- **Arquivo de cache corrompido ou diretório sem permissão:** é tratado como ausente e baixado de novo, ou usa o diretório alternativo. Coberto em Task 3 (`test_corrupt_cached_tile_refetched`, `test_cache_root_fallback`).
- **Latitude extrema ou fora do Web Mercator:** a latitude é limitada a ±85.0511 e não ocorre erro. Coberto em Task 3 (`test_latitude_clamped`).
- **Janela de batimetria toda NaN ou com 1 px:** relevo e composição não quebram e devolvem transparente. Coberto em Task 2 (`test_hillshade_tiny_and_all_nan`).
- **URL personalizada sem `{z}/{x}/{y}` ou sem https:** é rejeitada com mensagem. Coberto em Task 3 (`test_config_rejects_bad_url`).

## Ambiente de teste (Linux, nesta sessão)

```bash
python3 -m venv /tmp/claude-0/venv-ss && /tmp/claude-0/venv-ss/bin/pip install numpy rasterio matplotlib PySide6 pytest
```

Rode os testes de dentro da pasta da versão com `QT_QPA_PLATFORM=offscreen`. A suíte completa da 4.9 depende de GDAL/osgeo, numba e gravações privadas, então roda no Windows do usuário. Aqui rodam apenas os testes novos, junto com `python -m compileall`.

---

### Task 1: Snapshot da versão 4.10

**Files:**
- Create: `outputs/SonarStudio-v410-Mapa-test1/` (cópia de `outputs/SonarStudio-v49-Hybrid-beta4/`)
- Modify: `outputs/SonarStudio-v410-Mapa-test1/version.json`
- Modify: `sonarstudio-versions.json` (append, `latest`)
- Create: `docs/releases/4.10-Mapa-test.1.md`

**Interfaces:**
- Produces: pasta de trabalho para as tasks 2–5. Antes de copiar, conferir com `git ls-files` que nada é gerado ou privado.

- [ ] **Step 1:** `cp -r outputs/SonarStudio-v49-Hybrid-beta4 outputs/SonarStudio-v410-Mapa-test1` e remover qualquer `__pycache__`.
- [ ] **Step 2:** Em `version.json`:
  - `version`: `"4.10-Mapa-test.1"`
  - `created_utc`: data atual
  - nova chave `"basemap": "XYZ tiles opt-in (OSM default), disk cache 7 days, max 2 concurrent / 64 per view; no bulk prefetch"`
  - nova chave `"bathymetry_style": "hillshade, banded palette, opacity, display-only Chaikin contours with along-line labels; grid unchanged"`
  - `test_count` fica como está por enquanto; é atualizado na Task 5.
- [ ] **Step 3:** Em `sonarstudio-versions.json`, acrescentar `{"version":"4.10-Mapa-test.1","folder":"outputs/SonarStudio-v410-Mapa-test1","tag":"sonarstudio-v4.10-Mapa-test.1","notes_file":"docs/releases/4.10-Mapa-test.1.md"}` e mudar `latest`.
- [ ] **Step 4:** Criar `docs/releases/4.10-Mapa-test.1.md` com um título e um placeholder de uma linha. O texto completo entra na Task 5.
- [ ] **Step 5:** Rodar `python3 -c "import json;json.load(open('sonarstudio-versions.json'))"` e `python3 -m compileall -q outputs/SonarStudio-v410-Mapa-test1`. Os dois devem terminar sem erro.
- [ ] **Step 6:** Commit `chore: snapshot SonarStudio 4.10-Mapa-test.1 a partir da 4.9`.

### Task 2: `bathy_style.py`

**Files:**
- Create: `outputs/SonarStudio-v410-Mapa-test1/bathy_style.py`
- Test: `outputs/SonarStudio-v410-Mapa-test1/test_mapa410.py` (classe `BathyStyleTests`)

**Interfaces:**
- Produces:
  - `hillshade(depth: np.ndarray, cell: float, azimuth: float = 315., altitude: float = 45., z_factor: float = 1.) -> np.ndarray`: retorna float32 em [0,1], com NaN onde `depth` é NaN. A elevação é `-depth`, porque a profundidade é positiva para baixo. Usar `np.gradient` com espaçamento `cell`.
  - `banded(depth: np.ndarray, lo: float, hi: float, interval: float) -> np.ndarray`: normaliza `floor((d-lo)/interval)*interval` para [0,1] em relação a `(hi-lo)`, preservando NaN. Se `interval <= 0`, retorna a normalização contínua.
  - `compose(depth: np.ndarray, lo: float, hi: float, palette: str, *, interval: float | None = None, shade: np.ndarray | None = None, opacity: float = 1.) -> np.ndarray`: retorna RGBA uint8 de shape (H,W,4). Ordem: cor de `colormaps[palette]` sobre `banded` ou contínuo; depois `rgb *= 0.5 + 0.5*shade` quando há `shade`; depois alfa `round(255*opacity)` onde for válido e 0 onde for NaN.
  - `chaikin(points: np.ndarray, iterations: int = 2) -> np.ndarray`: shape (M,2). Linha aberta mantém as pontas exatas. Anel fechado (primeiro ponto igual ao último) continua fechado. Com menos de 3 pontos, retorna a entrada.
  - `label_positions(points: np.ndarray, spacing_px: float = 220., min_length_px: float = 80.) -> list[tuple[float, float, float]]`: recebe pontos em pixels de tela e retorna `(x, y, angulo_graus)`, com ângulo em (-90, 90]. Linhas menores que `min_length_px` retornam `[]`. Os rótulos ficam nas distâncias `spacing_px/2 + k*spacing_px` ao longo da linha, desde que não passem do comprimento total.

- [ ] **Step 1: Write the failing tests**

```python
class BathyStyleTests(unittest.TestCase):
 def test_hillshade_flat_is_sin_altitude(self):
  s=hillshade(np.full((8,8),10.),2.);np.testing.assert_allclose(s,np.sin(np.radians(45)),atol=1e-6)
 def test_hillshade_inclined_plane_constant_and_nan_preserved(self):
  d=np.tile(np.arange(10.),(10,1));d[3,3]=np.nan;s=hillshade(d,1.)
  self.assertTrue(np.isnan(s[3,3]));f=s[np.isfinite(s)];self.assertLess(np.ptp(f[(f>0)]),0.05) # interior quase constante
  self.assertTrue(((f>=0)&(f<=1)).all())
 def test_hillshade_tiny_and_all_nan(self):
  self.assertEqual(hillshade(np.array([[5.]]),1.).shape,(1,1))
  self.assertTrue(np.isnan(hillshade(np.full((4,4),np.nan),1.)).all())
  rgba=compose(np.full((4,4),np.nan),0,10,'Blues',shade=hillshade(np.full((4,4),np.nan),1.));self.assertEqual(rgba[...,3].max(),0)
 def test_banded_steps(self):
  np.testing.assert_allclose(banded(np.array([0.,.9,1.,2.5,10.]),0,10,1.),[0,0,.1,.2,1.])
  self.assertTrue(np.isnan(banded(np.array([np.nan]),0,10,1.))[0])
 def test_compose_opacity_and_shade(self):
  d=np.array([[1.,np.nan]]);a=compose(d,0,10,'Blues',opacity=.5);self.assertEqual(a.dtype,np.uint8)
  self.assertEqual(a[0,0,3],128);self.assertEqual(a[0,1,3],0)
  dark=compose(d,0,10,'Blues',shade=np.zeros_like(d));self.assertTrue((dark[0,0,:3]<=a[0,0,:3]).all())
 def test_chaikin_open_keeps_ends_and_closed_stays_closed(self):
  p=np.array([[0,0],[10,0],[10,10.]]);c=chaikin(p)
  np.testing.assert_array_equal(c[0],p[0]);np.testing.assert_array_equal(c[-1],p[-1]);self.assertGreater(len(c),len(p))
  r=np.array([[0,0],[10,0],[10,10],[0,0.]]);cr=chaikin(r);np.testing.assert_array_equal(cr[0],cr[-1])
  np.testing.assert_array_equal(chaikin(p[:2]),p[:2])
 def test_label_positions_spacing_and_upright(self):
  line=np.c_[np.linspace(500,0,51),np.zeros(51)] # da direita para a esquerda
  labels=label_positions(line,spacing_px=200);self.assertEqual(len(labels),3)
  self.assertAlmostEqual(labels[0][0],400,delta=1);self.assertTrue(all(-90<a<=90 for _,_,a in labels))
  self.assertEqual(label_positions(np.array([[0,0],[50,0.]])),[])
```

- [ ] **Step 2:** Rodar `cd outputs/SonarStudio-v410-Mapa-test1 && QT_QPA_PLATFORM=offscreen python -m pytest test_mapa410.py -k BathyStyle -v`. Esperado: FAIL com ImportError.
- [ ] **Step 3:** Implementar as cinco funções conforme o bloco Interfaces.
- [ ] **Step 4:** Rodar de novo. Esperado: 7 passed.
- [ ] **Step 5:** Commit `feat(4.10): estilo de batimetria com relevo, faixas e isóbatas suaves`.

### Task 3: `basemap.py`

**Files:**
- Create: `outputs/SonarStudio-v410-Mapa-test1/basemap.py`
- Test: `outputs/SonarStudio-v410-Mapa-test1/test_mapa410.py` (classe `BasemapTests`)

**Interfaces:**
- Produces:
  - Constantes:
    - `DEFAULT_URL`, `DEFAULT_ATTRIBUTION` e `USER_AGENT`, com os valores das Global Constraints;
    - `MAX_TILES_PER_VIEW = 64`;
    - `CACHE_DAYS = 7`;
    - `FAIL_BACKOFF_S = 60`;
    - `MAX_LAT = 85.05112878`.
  - `lonlat_to_tile(lon: float, lat: float, z: int) -> tuple[float, float]`: x,y fracionários, com latitude limitada a ±MAX_LAT.
  - `tile_bounds_3857(x: int, y: int, z: int) -> tuple[float, float, float, float]`: retorna `(left, bottom, right, top)` em metros EPSG:3857.
  - `zoom_for_resolution(m_per_px: float, lat: float, max_zoom: int = 19) -> int`: menor z com `156543.03392*cos(lat)/2**z <= m_per_px`, limitado a [0, max_zoom].
  - `@dataclass BasemapConfig(url: str = DEFAULT_URL, max_zoom: int = 19, attribution: str = DEFAULT_ATTRIBUTION, enabled: bool = False)`. `validate()` lança `ValueError` se a URL não começar com `https://` ou se faltar `{z}`, `{x}` ou `{y}`, e também se `max_zoom` estiver fora de 0–22. Também tem `state() -> dict` e `from_state(d: dict) -> BasemapConfig`, que ignora chaves desconhecidas e usa os padrões nas que faltarem.
  - `cache_root(env: Mapping[str, str] = os.environ) -> Path`: usa `LOCALAPPDATA/SonarStudio/tiles` se der para criar e gravar. Senão, usa `Path.home()/'.sonarstudio'/'tiles'`.
  - `class TileCache(root: Path, url: str, fetch: Callable[[str], bytes] | None = None, max_age_days: float = CACHE_DAYS, clock: Callable[[], float] = time.time)`:
    - `get(z, x, y) -> np.ndarray | None` retorna RGBA uint8 (256,256,4).
    - Disco válido e dentro da validade: usa o disco. Senão, baixa (o padrão é `http_fetch`), grava de forma atômica e decodifica.
    - Bytes que não decodificam contam como ausência.
    - Exceção no fetch faz `get` retornar `None` e bloqueia aquele tile por `FAIL_BACKOFF_S`.
    - `threading.BoundedSemaphore(2)` limita os downloads.
    - A decodificação usa `rasterio.io.MemoryFile`. Imagens de 1 ou 3 bandas recebem alfa 255.
  - `http_fetch(url: str, timeout: float = 10.) -> bytes`: `urllib.request` com o header `User-Agent: USER_AGENT`.
  - `tiles_for_view(bounds: tuple[float, float, float, float], crs, m_per_px: float, max_zoom: int) -> tuple[int, list[tuple[int, int]]]`: transforma bounds para EPSG:4326 com `rasterio.warp.transform_bounds`, escolhe o zoom e reduz z até ter no máximo `MAX_TILES_PER_VIEW` tiles.
  - `render_view(cache: TileCache, bounds, crs, width: int, height: int, m_per_px: float, max_zoom: int, cancel: Callable[[], bool] = lambda: False) -> np.ndarray | None`: retorna RGBA (height,width,4). Monta o mosaico 3857 e faz `reproject(..., dst_crs=crs, dst_transform=from_bounds(*bounds, width, height), resampling=bilinear)`. Retorna `None` se nenhum tile chegou ou se `cancel()` ficar verdadeiro.

- [ ] **Step 1: Write the failing tests**

Usar um fetcher falso que devolve um PNG sólido gerado com `rasterio.MemoryFile` e conta as chamadas. Usar `tempfile.TemporaryDirectory`.

```python
class BasemapTests(unittest.TestCase):
 def test_tile_math_known_values(self):
  self.assertEqual(tuple(int(v) for v in lonlat_to_tile(0,0,1)),(1,1))
  x,y=lonlat_to_tile(-46.6333,-23.5505,10);self.assertEqual((int(x),int(y)),(379,580))
  l,b,r,t=tile_bounds_3857(0,0,0);self.assertAlmostEqual(r,20037508.34,places=1);self.assertAlmostEqual(b,-20037508.34,places=1)
 def test_latitude_clamped(self):
  self.assertEqual(lonlat_to_tile(0,89.9,3),lonlat_to_tile(0,MAX_LAT,3))
 def test_zoom_for_resolution(self):
  self.assertEqual(zoom_for_resolution(1.,0),18);self.assertEqual(zoom_for_resolution(.01,0),19);self.assertEqual(zoom_for_resolution(1e6,0),0)
 def test_config_rejects_bad_url(self):
  for url in ['http://a/{z}/{x}/{y}.png','https://a/{z}/{x}.png']:
   with self.assertRaises(ValueError):BasemapConfig(url=url).validate()
  self.assertFalse(BasemapConfig().enabled);self.assertEqual(BasemapConfig.from_state({'max_zoom':17,'x':1}).max_zoom,17)
 def test_cache_hit_expiry_and_url_isolation(self): # 2a chamada não baixa; clock+8 dias baixa de novo; outra URL usa outra pasta
 def test_fetch_failure_returns_none_and_backs_off(self): # fetch levanta OSError: get→None; 2a chamada imediata não chama fetch; após clock+61 s chama
 def test_corrupt_cached_tile_refetched(self): # grava b'lixo' no caminho do tile: get baixa de novo e retorna array (256,256,4)
 def test_cache_root_fallback(self): # LOCALAPPDATA apontando para arquivo (não diretório) → resultado sob Path.home()
 def test_tile_count_capped_by_lowering_zoom(self): # bounds UTM 23S de 50 km com m_per_px=.1 → len(tiles)<=64
 def test_render_view_reprojects_solid_tiles(self): # tiles vermelhos sólidos, CRS EPSG:31983, 200x100 → shape (100,200,4), centro [255,0,0,255]
 def test_render_view_none_when_all_fail(self):
```

Cada teste com comentário recebe assertions que verificam exatamente o comportamento descrito no comentário.

- [ ] **Step 2:** Rodar `-k Basemap`. Esperado: FAIL com ImportError.
- [ ] **Step 3:** Implementar conforme o bloco Interfaces. Caminho do tile: `root/sha256(url)[:16]/z/x/y.tile`. Gravar em `.tmp` e depois fazer `replace`.
- [ ] **Step 4:** Rodar de novo. Esperado: 11 passed. Confirmar que nenhum teste chama `http_fetch`, mesmo que indiretamente; para isso, fazer patch de `basemap.http_fetch` para lançar exceção na classe de teste.
- [ ] **Step 5:** Commit `feat(4.10): tiles XYZ com cache em disco e reprojeção`.

### Task 4: Integração no mapa

**Files:**
- Create: `outputs/SonarStudio-v410-Mapa-test1/basemap_worker.py`
- Modify: `outputs/SonarStudio-v410-Mapa-test1/app.py`:
  - `MapView.__init__` (~l.99–128)
  - `render_raster`/`raster_image` (~l.188–222)
  - `paintEvent` (~l.224–314)
  - controles do mapa (~l.603–609)
  - `load_contours` (~l.1114–1126)
  - `save_project`/`open_project` e o restore em ~l.798
- Test: `test_mapa410.py` (classe `MapIntegrationTests`, com `QApplication` offscreen)

**Interfaces:**
- Consumes: `bathy_style.hillshade`, `compose`, `chaikin`, `label_positions`; `basemap.BasemapConfig`, `TileCache`, `cache_root`, `render_view`, `DEFAULT_ATTRIBUTION`.
- Produces:
  - `class BasemapLoader(QObject)` com o sinal `ready = Signal(object, QImage)`, que emite `(key, image)`.
    - Construtor: `__init__(self, cache_factory: Callable[[str], TileCache])`.
    - `request(key, bounds, crs, width, height, m_per_px, config)`: uma única thread de trabalho e só a requisição mais recente pendente. O `cancel` de `render_view` fica verdadeiro quando chega outra `key`. O resultado só é emitido se `key` ainda for a mais recente.
    - `shutdown()`.
  - Novos atributos do `MapView`:
    - `basemap_config: BasemapConfig`
    - `basemap_image: QImage | None`
    - `basemap_key`
    - `relief_visible = True`
    - `bands_visible = True`
    - `layer_opacity = 0.85`
    - `contour_interval = 1.`
    - `loader: BasemapLoader | None`
  - Novo método do `MapView`: `map_crs()`. Retorna `dataset.crs` ou `recording.crs` ou `None`.

Comportamento:

- `render_raster`:
  - Quando `basemap_config.enabled` e há `map_crs()`, chama `loader.request` com a vista atual. `key = (tuple(center), span, width, height, config.url)`.
  - Para o raster float, `raster_image` usa `compose(data.filled(nan), *depth_range, depth_palette, interval=contour_interval if bands_visible else None, shade=hillshade(..., cell=meters_per_pixel(), z_factor=3.) if relief_visible else None, opacity=layer_opacity if basemap_image is not None else 1.)`.
  - O mosaico SideScan (4 bandas ou uint8) só tem o alfa multiplicado por `layer_opacity` quando há fundo.
- `paintEvent`, nesta ordem:
  1. fundo liso `#142331`;
  2. `basemap_image`, se a key bater;
  3. raster;
  4. calor IA;
  5. isóbatas;
  6. trilha, objetos e medição, sem mudança;
  7. escala, norte e legenda;
  8. atribuição.
- Isóbatas: `load_contours` guarda `chaikin(points[::stride])`. No desenho, as maiores (múltiplos de `5*contour_interval`) usam 1.4 px e as menores 0.6 px, as duas na cor `#e5f0c9`. Os rótulos `f'{depth:g} m'` saem de `label_positions` aplicado aos pontos em tela das linhas maiores. O texto é desenhado rotacionado (`p.save(); p.translate; p.rotate; drawText; p.restore()`), com halo escuro de 3 px. Continua valendo a regra de não sobrepor, com a grade `occupied` já existente.
- Legenda com `bands_visible`: a rampa vertical existente passa a usar `banded` e mostra até 8 marcas de profundidade, espaçadas em múltiplos inteiros de `contour_interval`.
- Atribuição: texto `basemap_config.attribution` no canto inferior direito, com fundo semitransparente, desenhado sempre que `basemap_image` é desenhada.
- `contour_interval` vem de `bathy_result['settings']['contour_interval']` quando o resultado é carregado ou gerado; o padrão é 1.
- Controles novos na linha do mapa, depois de "Isóbatas":
  - `QCheckBox('Mapa de fundo')`;
  - `QCheckBox('Relevo')`, marcado;
  - `QCheckBox('Faixas')`, marcado;
  - `QLabel('Opacidade')` com `QSlider` de 20 a 100 e valor 85;
  - `QPushButton('Fonte do mapa…')`, que abre `QInputDialog` para URL, zoom máximo e atribuição, valida com `validate()` e mostra o erro no log.
- Primeira ativação de "Mapa de fundo": se `QSettings('SonarStudio','SonarStudio').value('basemap/consent')` não for `'1'`, abrir `QMessageBox.question` com o texto abaixo. Se o usuário recusar, a checkbox volta a ficar desmarcada.

  > "O mapa de fundo baixa imagens de {host da URL}. Cada pedido revela ao servidor a região visível do mapa. As imagens ficam em cache local por 7 dias. Deseja ativar?"
- Estado: `save_project` grava `data['map_style'] = {'basemap': config.state(), 'relief': ..., 'bands': ..., 'opacity': ...}` e a restauração lê esses valores com padrões. O consentimento não entra no projeto.
- Encerramento: `closeEvent` da janela chama `loader.shutdown()`.

- [ ] **Step 1: Write the failing tests**

```python
class MapIntegrationTests(unittest.TestCase):
 # setUpClass: QT_QPA_PLATFORM=offscreen, QApplication
 def test_loader_drops_stale_results(self): # cache_factory falso com render lento; request(k1) e logo request(k2): só k2 é emitido (QSignalSpy ou lista + processEvents até 5 s)
 def test_mapview_draws_basemap_under_bathymetry(self):
  # MapView 200x100 com recording fake (crs EPSG:31983, xy) e GeoTIFF float sintético em tempdir (rasterio)
  # basemap_image = QImage vermelho, basemap_key = key atual, layer_opacity=.5 → grab(): pixel central mistura vermelho com a cor da paleta (R>0 e diferente de ambos)
  # pixel fora do raster continua vermelho; texto de atribuição não quebra o render
 def test_basemap_off_by_default_no_request(self): # MapView novo: basemap_config.enabled False; loader.request nunca chamado após render_raster
 def test_contours_loaded_smoothed(self): # map.contours recebe saída de chaikin: len(points) > entrada e pontas iguais
```

- [ ] **Step 2:** Rodar `-k MapIntegration`. Esperado: FAIL.
- [ ] **Step 3:** Implementar `basemap_worker.py` e as mudanças em `app.py` descritas acima, sem tocar em outra lógica.
- [ ] **Step 4:** Rodar `QT_QPA_PLATFORM=offscreen python -m pytest test_mapa410.py -v`. Esperado: todos passam. Depois rodar `python -m compileall -q .`, que deve terminar sem erro.
- [ ] **Step 5:** Commit `feat(4.10): mapa de fundo opcional e visual de batimetria no mapa`.

### Task 5: Documentação e verificação final

**Files:**
- Modify: `docs/releases/4.10-Mapa-test.1.md`, `README.md` (seção curta "4.10-Mapa-test.1" e linha de créditos OSM), `outputs/SonarStudio-v410-Mapa-test1/version.json` (`test_count` = 142 + novos testes)

- [ ] **Step 1:** Nota de release em português, no estilo de `docs/releases/4.9-Hybrid-beta.4.md`. Deve dizer:
  - o que entrou;
  - que o mapa de fundo é opcional e começa desligado;
  - o aviso de privacidade;
  - a atribuição e as regras de uso do OSM (sem download em massa);
  - que a grade e as isóbatas exportadas não mudam;
  - que a validação foi parcial no Linux e que a suíte da 4.9 e a GUI precisam ser validadas no Windows.
- [ ] **Step 2:** No README, adicionar uma linha de crédito: "Mapa de fundo padrão: dados © colaboradores do OpenStreetMap (ODbL); tiles sujeitos à política de uso do OSM".
- [ ] **Step 3:** Rodar `QT_QPA_PLATFORM=offscreen python -m pytest outputs/SonarStudio-v410-Mapa-test1/test_mapa410.py -v` e `python -m compileall -q outputs/SonarStudio-v410-Mapa-test1`. Registrar a contagem real de testes no `version.json`.
- [ ] **Step 4:** Commit `docs(4.10): notas da versão Mapa-test.1` e push para `claude/cool-clarke-xwcsec`.
