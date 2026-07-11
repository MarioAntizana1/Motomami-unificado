"""
fb_display.py - Display via framebuffer nativo (mmap directo)
Sin fb_daemon externo. Escribe directo a /dev/fb1 y /dev/fb2.
"""
import mmap
import os
import sys

from PIL import Image, ImageDraw, ImageFont

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

# ── Rutas config ──
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from config_loader import FB1_PATH, FB2_PATH, DISP_W, DISP_H
except ImportError:
    FB1_PATH, FB2_PATH = "/dev/fb1", "/dev/fb2"
    DISP_W, DISP_H = 320, 240

_FONT_PATHS = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]

def _find_font(size=14):
    for p in _FONT_PATHS:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def _sysfs(fb_name, attr):
    path = f"/sys/class/graphics/{fb_name}/{attr}"
    with open(path) as f:
        return f.read().strip()


class FramebufferDisplay:
    """Acceso directo a un framebuffer (/dev/fbX) via mmap."""

    def __init__(self, fb_path="/dev/fb1"):
        self.fb_path = fb_path
        fn = os.path.basename(fb_path)
        try:
            w, h = _sysfs(fn, "virtual_size").split(",")
            self.width = int(w)
            self.height = int(h)
            self.bpp = int(_sysfs(fn, "bits_per_pixel"))
        except Exception:
            self.width, self.height, self.bpp = DISP_W, DISP_H, 16

        self.Bpp = self.bpp // 8
        self.buf_size = self.width * self.height * self.Bpp
        self._fd = os.open(self.fb_path, os.O_RDWR)
        self._mmap = mmap.mmap(
            self._fd, self.buf_size, mmap.MAP_SHARED,
            mmap.PROT_READ | mmap.PROT_WRITE
        )

    def _to_rgb565(self, img: Image.Image) -> bytes:
        if img.size != (self.width, self.height):
            img = img.resize((self.width, self.height))
        if img.mode != "RGB":
            img = img.convert("RGB")
        if _HAS_NUMPY:
            a = np.asarray(img, dtype=np.uint16)
            rgb565 = ((a[:, :, 0] >> 3) << 11) | ((a[:, :, 1] >> 2) << 5) | (a[:, :, 2] >> 3)
            return rgb565.astype("<u2").tobytes()
        # Fallback puro Python (lento)
        out = bytearray(self.buf_size)
        px = img.load()
        i = 0
        for y in range(self.height):
            for x in range(self.width):
                r, g, b = px[x, y]
                v = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
                out[i] = v & 0xFF
                out[i + 1] = (v >> 8) & 0xFF
                i += 2
        return bytes(out)

    def show(self, img: Image.Image):
        """Envía imagen PIL al framebuffer."""
        data = self._to_rgb565(img)
        self._mmap.seek(0)
        self._mmap.write(data)

    def blank(self):
        """Apaga la pantalla (pone todo en negro)."""
        self._mmap.seek(0)
        self._mmap.write(b"\x00" * self.buf_size)

    def close(self):
        self.blank()
        self._mmap.close()
        os.close(self._fd)


# ── Instancias globales (singleton por proceso) ──
_d1: FramebufferDisplay = None
_d2: FramebufferDisplay = None


def _get_fb1() -> FramebufferDisplay:
    global _d1
    if _d1 is None:
        _d1 = FramebufferDisplay(FB1_PATH)
    return _d1


def _get_fb2() -> FramebufferDisplay:
    global _d2
    if _d2 is None:
        _d2 = FramebufferDisplay(FB2_PATH)
    return _d2


# ── Compatibilidad con código existente ──
daemon_available = lambda: True
W, H = DISP_W, DISP_H


class FbDisplay:
    """
    Canvas unificado para 1 o 2 pantallas.
    disp_id=1 → /dev/fb1
    disp_id=2 → /dev/fb2
    disp_id=3 → canvas 640x240 que divide en fb1 (izq) y fb2 (der)
    """

    def __init__(self, disp_id=1):
        self.id = disp_id
        self.width = W * 2 if disp_id == 3 else W
        self.height = H
        self._img = Image.new("RGB", (self.width, self.height), (0, 0, 0))
        self._draw = ImageDraw.Draw(self._img)

        # Fuentes predefinidas
        self.font_title = _find_font(18)
        self.font       = _find_font(14)
        self.font_s     = _find_font(11)
        self.font_xs    = _find_font(9)
        self.font_big   = _find_font(40)

    def blank(self):
        self._img = Image.new("RGB", (self.width, self.height), (0, 0, 0))
        self._draw = ImageDraw.Draw(self._img)

    def draw(self) -> ImageDraw.Draw:
        return self._draw

    def image(self) -> Image.Image:
        return self._img

    def update(self):
        if self.id == 3:
            _get_fb1().show(self._img.crop((0, 0, W, H)))
            _get_fb2().show(self._img.crop((W, 0, W * 2, H)))
        elif self.id == 1:
            _get_fb1().show(self._img)
        else:
            _get_fb2().show(self._img)

    def resume(self):
        """Re-abre el framebuffer si fue cerrado."""
        pass  # Con mmap singleton no es necesario

    def suspend(self):
        """Placeholder para compatibilidad."""
        pass

    def close(self):
        self.blank()
        self.update()
