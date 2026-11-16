# Mapa de fundo e visual da batimetria — design

Data: 2026-11-16 · Status: aprovado

## Intenção

O usuário quer que a batimetria do SonarStudio fique "boa como a do ReefMaster". Na comparação, faltam duas coisas: um **mapa de fundo** (OpenStreetMap) por baixo da batimetria e um **visual mais bonito**. A implementação é clean-room: usa só conhecimento público de cartografia (XYZ tiles, hillshade, faixas de cor, suavização de linhas). Não copia código, nome, marca nem a aparência da interface do ReefMaster.

## Objetivos

1. Camada de mapa de fundo com tiles XYZ, reprojetados para o CRS projetado da gravação e desenhados sob o raster.
2. Visual da batimetria com relevo sombreado, paleta em faixas, transparência, isóbatas suavizadas com rótulos ao longo da curva e legenda.

## Não-objetivos

- Alterar a grade de profundidade, a interpolação ou os arquivos GeoTIFF/GPKG gerados.
- Exportar cartas para GPS, juntar várias gravações, baixar áreas grandes para uso offline.

## Anti-objetivos

- Enviar a localização a terceiros sem o usuário saber. O mapa de fundo começa desligado.
- Travar a interface esperando a rede.
- Violar a política de uso de tiles do OSM: requisições em massa, ausência de User-Agent ou de atribuição.

## Restrições

- Aplicativo Windows em PySide6, Python, rasterio, GDAL e matplotlib. Não entram dependências novas: HTTP via `urllib.request`.
- O mapa usa coordenadas projetadas sem rotação (`MapView.center`, `span`, `meters_per_pixel`).
- O projeto guarda cada versão numa pasta snapshot própria em `outputs/` e a registra em `sonarstudio-versions.json`.
- Os testes do mapa de fundo não podem acessar a rede.

## Abordagens consideradas

- **Mapa de fundo:**
  - **A, escolhida:** tiles online configuráveis, com OSM como padrão e cache em disco.
  - **B:** só arquivos locais. Mais privado, porém trabalhoso de preparar.
  - **A+B:** mais escopo. Fica para depois; a lógica de desenho é a mesma.
- **Visual:**
  - **1, escolhida:** mudar só a forma de desenhar.
  - **2:** trocar também a interpolação. Arriscado, porque muda números e testes existentes.

## Design

### Versão

Nova pasta `outputs/SonarStudio-v410-Mapa-test1`, copiada da 4.9-Hybrid-beta.4, com versão `4.10-Mapa-test.1`. Também entram uma nota em `docs/releases/` e o registro em `sonarstudio-versions.json`.

### `basemap.py` (novo)

- Matemática Web Mercator: conversão lon/lat ↔ tile para um zoom z, e escolha do zoom a partir dos metros por pixel da tela. O zoom é limitado ao máximo do servidor, 19 por padrão.
- `TileCache`:
  - Grava em `%LOCALAPPDATA%/SonarStudio/tiles/<hash do URL>/z/x/y.png`, com fallback para o diretório home.
  - Validade de 7 dias.
  - Busca com User-Agent `SonarStudio/<versão>`, sem e-mail nem identificação do usuário.
  - No máximo 2 downloads simultâneos e limite por vista (≤ 64 tiles).
  - Falhas de rede retornam `None` e não lançam exceção para a interface.
- Composição: monta os tiles da vista num mosaico EPSG:3857 e o reprojeta com `rasterio.warp.reproject` para o CRS da gravação, no tamanho da tela.
- Os downloads rodam numa thread de trabalho. Ao terminar, a vista é atualizada se ainda for a mesma.
- Configuração: URL modelo `{z}/{x}/{y}`, zoom máximo e texto de atribuição, salvos com o estado do projeto.

### `bathy_style.py` (novo, funções puras numpy)

- `hillshade(grid, cell, azimuth=315, altitude=45, z_factor)`: deve tratar NaN/nodata.
- `banded(values, lo, hi, interval)`: quantiza a profundidade em faixas alinhadas ao intervalo das isóbatas.
- `compose(depth, ...)`: aplica paleta em faixas × relevo e opacidade, e gera RGBA.
- `chaikin(points, iterations=2)`: suaviza a linha só para exibição e preserva as pontas.
- `label_positions(path, spacing_px)`: posições e ângulos dos rótulos ao longo da curva.

### Mudanças em `app.py` (mínimas)

- `MapView.paintEvent` desenha nesta ordem: mapa de fundo, batimetria com relevo e opacidade, isóbatas suavizadas e rotuladas, trilha e objetos, legenda e atribuição.
- No painel aparecem:
  - checkbox "Mapa de fundo", com aviso de privacidade na primeira ativação;
  - checkbox "Relevo";
  - slider "Opacidade";
  - opção "Faixas de cor".
- O mosaico SideScan (raster de 4 bandas) não muda, exceto pela opacidade sobre o fundo.

### Testes

Ficam em `test_mapa410.py`:
- conversão de tiles com valores conhecidos;
- escolha de zoom;
- cache com fetcher falso, incluindo expiração e falha;
- composição e reprojeção com tiles sintéticos;
- hillshade de um plano inclinado, que deve ser constante, e preservação de NaN;
- faixas de cor;
- Chaikin preservando as pontas;
- rótulos.

A suíte da 4.9 continua passando.

## Fica a critério do implementador

Nomes internos, layout exato dos controles, cores dos rótulos e da legenda e detalhes do threading, desde que a interface não trave.
