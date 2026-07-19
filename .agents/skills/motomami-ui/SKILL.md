---
name: motomami-ui
description: "Diseño UI moderno para ST7789 320×240: sistema de tema, tipografía semántica, layout helpers, componentes reutilizables, paletas por app, patrones HUD/automotive."
risk: safe
source: personal
date_added: "2026-07-17"
---

# MotoMami UI — Diseño Moderno para ST7789

## Purpose

Sistema de diseño para las pantallas ST7789 del MotoMami. Inspirado en UI automotriz minimalista, dark theme, flat design con acentos sutiles. Resuelve los problemas actuales: colores harcodeados, layouts sin helpers, componentes duplicados, y tipografía inconsistente.

## Use this when

- Crear una nueva app en `src/apps/`
- Rediseñar la interfaz de una app existente
- Añadir nuevos componentes visuales
- Estandarizar la apariencia entre apps

## Design Philosophy

| Principio | Razón |
|-----------|-------|
| **Dark theme primero** | Ahorra batería en ST7789, mejor contraste en exteriores, estética automotriz |
| **Alto contraste** | Legible en moto con luz solar directa |
| **Flat design con acentos** | Sin somnias/neumorphism que se ven mal en RGB565 sin alpha |
| **Jerarquía clara** | Tamaño de fuente + color, no profundidad fingida |
| **Componentes modulares** | Un progress bar, no 3 copias |
| **Información densa pero limpia** | Cada pixel cuenta en 320×240 |

Inspiración: automotive HUD, Apple CarPlay, minimal dark dashboards, victron energy tiles.

## Sistema de Color

### Tema Base (`src/libs/theme.py`) — centralized palette

```python
from dataclasses import dataclass

@dataclass
class Theme:
    # Backgrounds
    BG:        tuple = (0, 0, 0)         # Fondo principal
    BG_DIM:    tuple = (10, 10, 15)       # Panel/card
    BG_MID:    tuple = (20, 22, 30)       # Header oscuro
    BG_LIGHT:  tuple = (35, 38, 50)       # Hover/selección

    # Text
    TEXT:      tuple = (220, 220, 230)    # Texto principal
    TEXT_DIM:  tuple = (130, 135, 150)    # Texto secundario
    TEXT_MUTED:tuple = (80, 85, 100)      # Labels/captions

    # Accent (por app, ver paletas abajo)
    ACCENT:    tuple = (100, 200, 255)    # Cyan (video)
    ACCENT_DIM:tuple = (20, 60, 90)       # Fondo hover

    # Semantic
    GOOD:      tuple = (0, 220, 80)       # OK/fix
    WARN:      tuple = (255, 180, 0)      # Advertencia
    ERROR:     tuple = (255, 60, 60)      # Error
    INFO:      tuple = (80, 180, 255)     # Info
```

### Paletas por App

```python
THEMES = {
    "main_menu":   Theme(ACCENT=(100, 255, 100), ACCENT_DIM=(20, 60, 20)),
    "gps":         Theme(ACCENT=(0, 220, 80),    ACCENT_DIM=(0, 40, 20)),
    "music":       Theme(ACCENT=(200, 100, 255), ACCENT_DIM=(40, 20, 60)),
    "video":       Theme(ACCENT=(0, 200, 255),   ACCENT_DIM=(0, 40, 60)),
    "connections": Theme(ACCENT=(80, 180, 255),  ACCENT_DIM=(0, 20, 50)),
    "doom":        Theme(ACCENT=(255, 80, 80),   ACCENT_DIM=(60, 20, 20)),
    "bluetooth":   Theme(ACCENT=(80, 160, 255),  ACCENT_DIM=(20, 30, 60)),
}

def get_theme(app_name="main_menu") -> Theme:
    return THEMES.get(app_name, Theme())
```

## Tipografía

### Font Sizes Semánticos

```python
FONT_SIZES = {
    "huge":  40,   # Splash / velocidad GPS
    "big":   32,   # Valores grandes (km/h, RPM)
    "title": 18,   # Títulos de pantalla
    "body":  14,   # Cuerpo / items menú
    "small": 11,   # Labels secundarios
    "xs":     9,   # Footnotes, status bar
}
```

### Helper de Fuente

```python
def _find_font(size=14):
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]
    for p in paths:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()
```

### Fonts Pre-cargadas en FbDisplay

```python
self.font_huge  = _find_font(40)   # .font_huge
self.font_big   = _find_font(32)   # .font_big
self.font_title = _find_font(18)   # .font_title
self.font       = _find_font(14)   # .font
self.font_s     = _find_font(11)   # .font_s
self.font_xs    = _find_font(9)    # .font_xs
```

## Layout Helpers

### Constantes

```python
W = 320          # Ancho por pantalla
H = 240          # Alto
PANEL_W = 320    # Split point for dual screen
HEADER_H = 24    # Altura header estandarizada
STATUS_H = 16    # Altura status bar
ITEM_H = 24      # Altura item menú
PAD = 8          # Padding general
PAD_S = 4        # Padding pequeño
MARGIN = 3       # Margen entre elementos
```

### Funciones Helper

```python
# Texto centrado horizontalmente
def center_text(draw, text, y, font, fill, w=W):
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    x = (w - tw) // 2
    draw.text((x, y), text, font=font, fill=fill)

# Texto alineado a la derecha
def right_text(draw, text, y, font, fill, w=W, pad=8):
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    x = w - tw - pad
    draw.text((x, y), text, font=font, fill=fill)

# Header estandarizado
def draw_header(draw, title, theme, w=W):
    draw.rectangle([(0, 0), (w-1, HEADER_H-1)], fill=theme.BG_MID)
    draw.text((PAD, PAD_S), title, font=font_title, fill=theme.ACCENT)

# Status bar
def draw_status_bar(draw, text_left, text_right, theme, w=W):
    y = H - STATUS_H
    draw.rectangle([(0, y), (w-1, H-1)], fill=theme.BG_MID)
    draw.text((PAD_S, y+2), text_left, font=font_xs, fill=theme.TEXT_DIM)
    right_text(draw, text_right, y+2, font_xs, theme.TEXT_DIM, w)

# Menú vertical con selección
def draw_menu(draw, items, selected, theme, start_y=HEADER_H+4, w=W):
    for i, item in enumerate(items):
        y = start_y + i * ITEM_H
        if i == selected:
            draw.rectangle([(MARGIN, y), (w-MARGIN, y+ITEM_H-2)],
                           fill=theme.ACCENT_DIM)
        label = f"> {item}" if i == selected else f"  {item}"
        draw.text((PAD, y+2), label, font=font, fill=theme.TEXT)
```

## Componentes Reutilizables

### Progress Bar

```python
def draw_progress_bar(draw, x, y, w, h, pct, color, bg_color=None, outline=True):
    if bg_color is None:
        bg_color = (20, 20, 30)
    if outline:
        draw.rectangle([(x, y), (x+w, y+h)], outline=(60, 60, 80))
    else:
        draw.rectangle([(x, y), (x+w, y+h)], fill=bg_color)
    fill_w = max(2, int(w * pct / 100))
    draw.rectangle([(x+1, y+1), (x+fill_w-1, y+h-1)], fill=color)
```

### Status Card (tile informativo estilo victron)

```python
def draw_card(draw, x, y, w, h, title, value, unit, accent):
    draw.rectangle([(x, y), (x+w, y+h)], fill=(12, 14, 20), outline=accent)
    draw.text((x+4, y+4), title, font=font_xs, fill=(130, 135, 150))
    mid = y + h//2 - 8
    draw.text((x+6, mid), str(value), font=font_big, fill=accent)
    tw = draw.textbbox((0, 0), unit, font=font_s)[2]
    draw.text((x+w-tw-4, mid+4), unit, font=font_s, fill=(130, 135, 150))
```

### Gauge Circular (HUD automotriz, simplificado)

```python
def draw_gauge(draw, cx, cy, r, pct, accent, label, value):
    # Arco de fondo
    draw.arc([(cx-r, cy-r), (cx+r, cy+r)], 135, 405, fill=(30, 32, 40), width=6)
    # Arco de valor
    end_angle = 135 + int(270 * pct / 100)
    draw.arc([(cx-r, cy-r), (cx+r, cy+r)], 135, end_angle, fill=accent, width=6)
    # Valor central
    bbox = draw.textbbox((0, 0), str(value), font=font_big)
    draw.text((cx - (bbox[2]-bbox[0])//2, cy-12), str(value), font=font_big, fill=accent)
    # Label
    bbox = draw.textbbox((0, 0), label, font=font_xs)
    draw.text((cx - (bbox[2]-bbox[0])//2, cy+8), label, font=font_xs, fill=(130, 135, 150))
```

### Split Panel (dual screen)

```python
def draw_split_panel(draw, theme, w=640):
    # Línea divisoria
    draw.line([(319, 0), (319, H-1)], fill=theme.BG_LIGHT, width=1)
```

## Patrón de App

```python
class BaseApp:
    def __init__(self, input_mgr, fb, state, theme_name="main_menu"):
        self._input = input_mgr
        self._fb = fb
        self._state = state
        self._theme = get_theme(theme_name)
        self._running = True

    def run(self):
        self._render()
        while self._running:
            evt = self._input.get_event(timeout=0.05)
            if evt:
                self._handle(evt[0])
                self._render()
            self._on_idle()  # actualizaciones periódicas

    def _render(self):
        self._fb.blank()
        d = self._fb.draw()
        self._draw_content(d)
        self._fb.update()

    def _draw_content(self, d):
        draw_header(d, self._title, self._theme)

    def _handle(self, action): ...
    def _on_idle(self): ...
```

## Inspiración Visual (de referencias reales)

| Referencia | Concepto | Adaptación |
|------------|----------|------------|
| s1panel | Dual rings CPU/RAM con glow, sparklines | Gauges circulares para velocidad/altitud GPS |
| LCARS (Star Trek) | Pill-capped bars, colores planos, sidebars | Separadores coloridos, barras de estado |
| Victron VRM | Tiles de energía con color semántico | Cards de estado GPS/sistema |
| Nebula Monitor | GitHub dark palette, paginación | Paleta oscura, navegación por grupos |
| Apple CarPlay | Clean, iconos modulares, max contraste | Headers limpios, iconos simples |
| Car HUD | Gauges analógicos, HUD heads-up | Gauge circular simplificado para velocidad |
| Alan Edwardes | Partial updates, dirty rectangles | Optimización de rendimiento |
| EV3 display | Bitmap fonts para tiny screens | `DejaVuSans-Bold.ttf` sizes 9-40 |

## Performance Tips

- **Pre-renderizar textos estáticos** que no cambian (labels, headers) en una `Image` aparte
- **Usar `textbbox()` para centrado** en lugar de guesswork
- **Cachear `ImageDraw.Draw`** no crear nuevo cada frame
- **Dirty regions**: enviar solo el rectángulo que cambió
- **Evitar `ImageFont.load_default()`** es muy pequeño (8px), usar TTF
- **numpy** para conversión RGB565 (ya implementado en `fb_display.py`)

## Errores Comunes

| Problema | Causa | Solución |
|----------|-------|----------|
| Texto cortado | Coordenada y + font_height > 240 | Usar `textbbox()` para medir |
| Header de altura inconsistente | Cada app usa su propio valor | Usar `HEADER_H = 24` |
| Panel derecho off-by-1 | 320 vs 321 | Usar `PANEL_W = 320` consistente |
| Colores quemados | RGB > 255 o < 0 | Validar con `max(0, min(255, v))` |
| Font no encontrada | TTF no instalado | `sudo apt install fonts-dejavu-core` |
| Flicker en actualización | `blank()` completo + re-dibujo | Usar dirty region o double buffer |

## Key Files

| File | Role |
|------|------|
| `src/libs/fb_display.py` | Core display + fonts precargadas |
| `src/apps/main_menu.py` | App ejemplo con menú completo |
| `src/apps/music_player_app.py` | App ejemplo con progress bar + split |
| `src/apps/gps_display_app.py` | App ejemplo con gauges + status |
| `src/core/input_manager.py` | Navegación UP/DOWN/ENTER/BACK |
