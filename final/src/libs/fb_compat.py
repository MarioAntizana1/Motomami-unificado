"""fb_compat.py - Compatibilidad con la API antigua de DualDisplay/DisplayST7789
================================================================================
video_player.py (y vp_player.VideoPlayer) fueron escritos contra la API antigua
de vp_display.py: DualDisplay.get_main()/get_secondary(), y metodos como
show_files(), show_now_playing(), show_message(), show_image(), suspend()/resume().

Esa API antigua hablaba directo con el bus SPI via busio+digitalio, lo cual ya
NO funciona: los pines CS/DC/RST/SCLK/MOSI ahora los posee el driver de kernel
que expone las pantallas como /dev/fb1 y /dev/fb2 (fbtft / panel driver).

Este modulo implementa la MISMA API antigua, pero escribiendo directamente al
framebuffer nativo via fb_display.FramebufferDisplay (mmap de /dev/fbX), igual
que ya hacen main_menu.py, music_player.py, doom_launcher.py y gps_display_app.py.

Sin GPIO, sin SPI, sin conflictos.
"""
import os
from PIL import Image, ImageDraw, ImageFont

from fb_display import FramebufferDisplay

_FONT_DIR = "/usr/share/fonts/truetype/dejavu/"


def _font(size, bold=False):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(os.path.join(_FONT_DIR, name), size)
    except Exception:
        return ImageFont.load_default()


class FbCompatDisplay:
    """Envuelve UN FramebufferDisplay nativo con la API antigua de DisplayST7789."""

    def __init__(self, fb_path):
        self._suspended = False
        self.fb = None
        try:
            self.fb = FramebufferDisplay(fb_path)
            self.W, self.H = self.fb.width, self.fb.height
        except Exception as e:
            print(f"[FbCompat] {fb_path} no disponible: {e}")
            self.W, self.H = 320, 240
        self.font = _font(14)
        self.font_s = _font(11)

    def ok(self):
        return self.fb is not None

    def suspend(self):
        # Ya no hay bus SPI que liberar, pero mantenemos el metodo para que
        # el resto del codigo (que llama suspend()/resume() alrededor del
        # video) no necesite cambiar.
        self._suspended = True

    def resume(self):
        self._suspended = False

    def clear(self):
        if self._suspended or not self.ok():
            return
        try:
            self.fb.show(Image.new("RGB", (self.W, self.H), (0, 0, 0)))
        except Exception:
            pass

    def show_image(self, img):
        """Muestra una PIL Image ya renderizada. Usado por vp_player.VideoPlayer
        para pushear cada frame de video."""
        if self._suspended or not self.ok():
            return
        try:
            self.fb.show(img)
        except Exception:
            pass

    def show_files(self, files, selected=0, playing_idx=-1, scroll=0, folder=""):
        if self._suspended or not self.ok():
            return
        img = Image.new("RGB", (self.W, self.H), (5, 5, 20))
        draw = ImageDraw.Draw(img)
        title = os.path.basename(folder) or "/"
        draw.text((5, 2), title, font=self.font, fill=(0, 200, 255))
        draw.line([(0, 20), (self.W, 20)], fill=(40, 40, 60))

        y = 25
        for idx, name, is_playing in files:
            if idx == selected:
                color, prefix = (255, 255, 255), "> "
            elif is_playing:
                color, prefix = (0, 255, 100), "> "
            else:
                color, prefix = (180, 180, 200), "  "
            draw.text((5, y), f"{prefix}{name[:22]}", font=self.font_s, fill=color)
            y += 14

        if not files:
            draw.text((10, 40), "No hay videos", font=self.font, fill=(200, 100, 0))
            draw.text((10, 60), "Pon MP4 en movies/", font=self.font_s, fill=(120, 120, 120))

        draw.rectangle([(1, 1), (self.W - 2, self.H - 2)], outline=(0, 100, 150), width=1)
        try:
            self.fb.show(img)
        except Exception:
            pass

    def show_now_playing(self, filename, pos=0, dur=0, status=">"):
        if self._suspended or not self.ok():
            return
        img = Image.new("RGB", (self.W, self.H), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        name = os.path.basename(filename)[:20]
        draw.text((5, 5), f"{status} {name}", font=self.font, fill=(0, 255, 120))

        if dur > 0:
            prog = min(pos / dur, 1.0)
            bw = self.W - 14
            bx, by = 7, 30
            draw.rectangle([(bx, by), (bx + bw, by + 8)], outline=(60, 60, 80))
            if prog > 0:
                draw.rectangle([(bx, by), (bx + int(bw * prog), by + 8)], fill=(0, 200, 255))

        pt = f"{int(pos // 60):02d}:{int(pos % 60):02d}"
        dt = f"{int(dur // 60):02d}:{int(dur % 60):02d}"
        draw.text((7, 44), f"{pt} / {dt}", font=self.font_s, fill=(200, 200, 200))

        for i, t in enumerate(["A=Play/Pausa  B=Volver", "X=Vol-  Y=Vol+", "LB/RB=15s"]):
            draw.text((7, 65 + i * 14), t, font=self.font_s, fill=(100, 100, 120))

        draw.rectangle([(1, 1), (self.W - 2, self.H - 2)], outline=(0, 150, 80), width=1)
        try:
            self.fb.show(img)
        except Exception:
            pass

    def show_message(self, text, line=0, color=(255, 255, 255)):
        if self._suspended or not self.ok():
            return
        img = Image.new("RGB", (self.W, self.H), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        y = line
        for row in str(text).split("\n"):
            draw.text((5, y), row, font=self.font, fill=color)
            y += 16
        try:
            self.fb.show(img)
        except Exception:
            pass


class DualDisplay:
    """Compatibilidad con vp_display.DualDisplay, pero via /dev/fb1 + /dev/fb2
    nativos en lugar de SPI directo.

    #1 (/dev/fb1) - info principal (navegador o reproduccion)
    #2 (/dev/fb2) - secundaria (info / portada)
    """

    def __init__(self):
        self.display1 = FbCompatDisplay("/dev/fb1")
        self.display2 = FbCompatDisplay("/dev/fb2")
        self.initialized = self.display1.ok() or self.display2.ok()
        print(f"[FbCompat] #1={'SI' if self.display1.ok() else 'NO'} "
              f"#2={'SI' if self.display2.ok() else 'NO'}")

    def get_main(self):
        if self.display1.ok():
            return self.display1
        return self.display2

    def get_secondary(self):
        if self.display2.ok():
            return self.display2
        return None

    def ok(self):
        return self.initialized

    def clear_all(self):
        self.display1.clear()
        self.display2.clear()
