---
name: motomami-pantallas
description: "Framebuffer dual ST7789 para Raspberry Pi: kernel driver fbtft, mmap a /dev/fb{1,2}, PIL ImageDraw, FbDisplay unified canvas, RGB565, partial updates, debugging."
risk: safe
source: personal
date_added: "2026-07-17"
---

# MotoMami Pantallas — ST7789 Framebuffer Dual

## Purpose

Guía para trabajar con las dos pantallas ST7789 (320×240, RGB565) del MotoMami a través del framebuffer del kernel Linux. El driver fbtft gestiona el SPI directamente; la app solo escribe a `/dev/fb1` y `/dev/fb2` vía `mmap`.

## Use this when

- Crear o modificar código de renderizado en `src/`
- Debuggear pantallas (blanco, congeladas, resolución incorrecta)
- Optimizar rendimiento de dibujo
- Configurar el kernel driver

## Architecture

```
App (PIL ImageDraw)
  → FbDisplay (src/libs/fb_display.py)
    → mmap a /dev/fb1 y /dev/fb2
      → kernel fbtft driver (SPI)
        → ST7789 panel #1 (CS=GPIO17) y #2 (CS=GPIO24)
```

**Resolución**: 320×240 por pantalla (landscape, rotation=1)  
**Formato píxel**: RGB565 (16-bit, 5R+6G+5B)  
**Framebuffer size**: 320×240×2 = 153,600 bytes por pantalla  
**Bus SPI**: 40 MHz, compartido (CS separados)

## Kernel Driver (fbtft)

Activado en `/boot/config.txt`:

```
dtoverlay=mi-paneltuning,cs=17,dc=27,rst=22,width=320,height=240
dtoverlay=mi-paneltuning,cs=24,dc=25,rst=23,width=320,height=240
```

Crea los dispositivos `/dev/fb1` y `/dev/fb2`. Verificar con:

```bash
fbset -fb /dev/fb1
fbset -fb /dev/fb2
sudo cat /sys/class/graphics/fb1/name   # → "st7789"
sudo cat /sys/class/graphics/fb2/name
```

**Problemas comunes**:  
- `fbset` no muestra /dev/fb2 → dt-overlay mal, revisar pines CS/RST/DC  
- Pantalla en blanco → backlight (GPIO) o contraseña en config.txt  
- Artefactos → velocidad SPI muy alta (bajar a 24 MHz)

## API Framebuffer — `FramebufferDisplay`

Archivo: `src/libs/fb_display.py`

```python
class FramebufferDisplay:
    def __init__(self, fb_path="/dev/fb1", width=320, height=240):
        self._fd = os.open(fb_path, os.O_RDWR)
        self._mmap = mmap.mmap(self._fd, width * height * 2, flags=mmap.MAP_SHARED,
                               prot=mmap.PROT_WRITE, offset=0)

    def render(self, image: Image.Image):
        # PIL Image (RGB) → bytes RGB565
        arr = np.array(image.convert("RGB"))
        r = (arr[:,:,0].astype(np.uint16) >> 3) << 11
        g = (arr[:,:,1].astype(np.uint16) >> 2) << 5
        b =  arr[:,:,2].astype(np.uint16) >> 3
        rgb565 = (r | g | b).astype('<u2').tobytes()
        self._mmap.seek(0)
        self._mmap.write(rgb565)
```

## Unified Canvas — `FbDisplay`

```python
class FbDisplay:
    def __init__(self, disp_id=3):
        # disp_id=1 → solo fb1
        # disp_id=2 → solo fb2
        # disp_id=3 → dual canvas 640×240, split automático
        self.width = 320 if disp_id in (1,2) else 640
        self.height = 240
        self._img = Image.new("RGB", (self.width, self.height), (0, 0, 0))
        self._fb1 = FramebufferDisplay("/dev/fb1")
        self._fb2 = FramebufferDisplay("/dev/fb2") if disp_id in (2,3) else None
        # Fonts precargadas semánticas
        self.font_big   = _find_font(32)
        self.font_title = _find_font(18)
        self.font       = _find_font(14)
        self.font_s     = _find_font(11)
        self.font_xs    = _find_font(9)

    def draw(self) -> ImageDraw.Draw:
        return ImageDraw.Draw(self._img)

    def blank(self):
        self._img = Image.new("RGB", (self.width, self.height), (0, 0, 0))

    def update(self):
        w = 320
        left = self._img.crop((0, 0, w, self.height))
        right = self._img.crop((w, 0, self.width, self.height))
        self._fb1.render(left)
        if self._fb2:
            self._fb2.render(right)
```

## RGB565 Conversion

```python
def rgb888_to_rgb565(r, g, b) -> int:
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
```

**Importante**: byte order little-endian en framebuffer. Usar `'<u2'` en numpy.

## Drawing Patterns

```python
# Header bar (estandarizar altura 24px)
d.rectangle([(0, 0), (W - 1, 23)], fill=ACCENT, outline=ACCENT_LIGHT)
d.text((8, 4), "TÍTULO", font=self._fb.font_title, fill=TEXT)

# Status bar (abajo, 16px)
d.rectangle([(0, H - 16), (W - 1, H - 1)], fill=BG_DARK)
d.text((4, H - 14), "status", font=self._fb.font_xs, fill=TEXT_DIM)

# Menú con selección
for i, item in enumerate(items):
    y = HEADER_H + 4 + i * ITEM_H
    if i == selected:
        d.rectangle([(2, y), (W - 2, y + ITEM_H - 2)], fill=ACCENT_DIM)
    d.text((10, y + 2), item, font=self._fb.font, fill=TEXT)
```

## Performance

- **Partial updates**: reusar la misma `Image` y solo modificar regiones
- **Text caching**: pre-renderizar textos estáticos con `ImageDraw.text()` una vez
- **Evitar `blank()` completo** si solo cambia una sección
- **Usar `numpy` para la conversión RGB565** (mucho más rápido que bucles Python)
- FPS objetivo: 15-30 FPS para animaciones, 1-5 FPS para dashboards

## Debugging

```python
# Test pattern: barras de color
def test_pattern(d, fb):
    img = Image.new("RGB", (320, 240))
    draw = ImageDraw.Draw(img)
    for x in range(320):
        r = int(255 * x / 319)
        draw.line([(x, 0), (x, 239)], fill=(r, 255 - r, 128))
    fb.render(img)

# Clear screen
def clear(fb):
    fb.render(Image.new("RGB", (320, 240), (0, 0, 0)))

# Información del framebuffer
def fb_info(path):
    with open(path, "rb") as f:
        f.seek(0)
        data = f.read()
    return f"{path}: {len(data)} bytes ({len(data)//(320*2)} líneas})"
```

## Key Files

| File | Role |
|------|------|
| `src/libs/fb_display.py` | Core: FramebufferDisplay + FbDisplay |
| `src/config_loader.py` | Config: paths fb1/fb2, w/h |
| `config.ini.example` | Template de configuración |
| `deploy/` | systemd service para el main |
