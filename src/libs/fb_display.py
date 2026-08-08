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
    from config_loader import (
        FB1_PATH, FB2_PATH, DISP_W, DISP_H, DISPLAY_MODE,
        HDMI_FB_PATH, HDMI_W, HDMI_H,
    )
except ImportError:
    FB1_PATH, FB2_PATH = "/dev/fb1", "/dev/fb2"
    DISP_W, DISP_H = 320, 240
    DISPLAY_MODE, HDMI_FB_PATH, HDMI_W, HDMI_H = "dual", "/dev/fb0", 1280, 800

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


def _sysfs_int(fb_name, attr, fallback):
    try:
        return int(_sysfs(fb_name, attr))
    except (OSError, ValueError):
        return fallback


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
        self.stride = _sysfs_int(fn, "stride", self.width * self.Bpp)
        self.buf_size = self.stride * self.height
        self._aspect_fit = DISPLAY_MODE == "hdmi" and self.fb_path == HDMI_FB_PATH
        self._fd = os.open(self.fb_path, os.O_RDWR)
        self._mmap = mmap.mmap(
            self._fd, self.buf_size, mmap.MAP_SHARED,
            mmap.PROT_READ | mmap.PROT_WRITE
        )

    def _row_pad(self, data: bytes, row_bytes: int) -> bytes:
        if self.stride == row_bytes:
            return data
        rows = []
        for y in range(self.height):
            row = data[y * row_bytes:(y + 1) * row_bytes]
            rows.append(row + b"\x00" * max(0, self.stride - row_bytes))
        return b"".join(rows)

    def _to_native(self, img: Image.Image) -> bytes:
        if img.size != (self.width, self.height):
            img = img.resize((self.width, self.height))
        if img.mode != "RGB":
            img = img.convert("RGB")

        if _HAS_NUMPY:
            a = np.asarray(img, dtype=np.uint16)
            if self.bpp == 16:
                rgb565 = ((a[:, :, 0] >> 3) << 11) | ((a[:, :, 1] >> 2) << 5) | (a[:, :, 2] >> 3)
                return self._row_pad(rgb565.astype("<u2").tobytes(), self.width * 2)
            rgb = a.astype(np.uint8)
            if self.bpp == 32:
                # XRGB8888 en little-endian framebuffer: B,G,R,X.
                native = np.empty((self.height, self.width, 4), dtype=np.uint8)
                native[:, :, 0] = rgb[:, :, 2]
                native[:, :, 1] = rgb[:, :, 1]
                native[:, :, 2] = rgb[:, :, 0]
                native[:, :, 3] = 0
                return self._row_pad(native.tobytes(), self.width * 4)
            if self.bpp == 24:
                return self._row_pad(rgb.tobytes(), self.width * 3)

        # Fallback puro Python (RGB565 o framebuffer no estandar).
        if self.bpp == 16:
            out = bytearray(self.width * self.height * 2)
        elif self.bpp == 32:
            out = bytearray(self.width * self.height * 4)
        else:
            out = bytearray(self.width * self.height * 3)
        px = img.load()
        i = 0
        for y in range(self.height):
            for x in range(self.width):
                r, g, b = px[x, y]
                if self.bpp == 16:
                    v = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
                    out[i:i + 2] = v.to_bytes(2, "little")
                    i += 2
                elif self.bpp == 32:
                    out[i:i + 4] = bytes((b, g, r, 0))
                    i += 4
                else:
                    out[i:i + 3] = bytes((r, g, b))
                    i += 3
        return self._row_pad(bytes(out), self.width * self.Bpp)

    def _write(self, img: Image.Image):
        data = self._to_native(img)
        self._mmap.seek(0)
        self._mmap.write(data)

    def show_aspect_fit(self, img: Image.Image):
        """Dibuja centrado sin deformar, usado por el framebuffer HDMI."""
        if img.mode != "RGB":
            img = img.convert("RGB")
        scale = min(self.width / img.width, self.height / img.height)
        size = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
        fitted = img.resize(size, Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (self.width, self.height), (0, 0, 0))
        canvas.paste(fitted, ((self.width - size[0]) // 2, (self.height - size[1]) // 2))
        self._write(canvas)

    def show(self, img: Image.Image):
        """Envía imagen PIL al framebuffer."""
        if self._aspect_fit:
            self.show_aspect_fit(img)
        else:
            self._write(img)

    def write_rgb565(self, data: bytes):
        """Escritura raw RGB565 little-endian (bytes exactos width*height*2).
        Ideal para frames de video desde ffmpeg (pix_fmt rgb565le)."""
        if self.bpp != 16:
            return
        n = self.width * self.height * 2
        self._mmap.seek(0)
        if self.stride == self.width * 2 and len(data) >= n:
            self._mmap.write(data[:n])
        else:
            row = self.width * 2
            for y in range(self.height):
                src = data[y * row:(y + 1) * row]
                self._mmap.seek(y * self.stride)
                self._mmap.write(src)

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
_hdmi: FramebufferDisplay = None


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


def _get_hdmi() -> FramebufferDisplay:
    global _hdmi
    if _hdmi is None:
        _hdmi = FramebufferDisplay(HDMI_FB_PATH)
    return _hdmi


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

    def __init__(self, disp_id=1, output=None, size=None):
        self.id = disp_id
        self.output = output or ("hdmi" if DISPLAY_MODE == "hdmi" else "dual")
        default_size = (W * 2, H) if disp_id == 3 else (W, H)
        self.width, self.height = size or default_size
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
        if self.output == "hdmi":
            _get_hdmi().show(self._img)
        elif self.output == "dual" and self.id == 3:
            _get_fb1().show(self._img.crop((0, 0, W, H)))
            _get_fb2().show(self._img.crop((W, 0, W * 2, H)))
        elif self.output == "dual" and self.id == 1:
            _get_fb1().show(self._img)
        elif self.output == "dual":
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
