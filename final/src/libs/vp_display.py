"""vp_display.py - Pantallas ST7789 duales de 2"" via SPI"""
import os
import sys
import time
import threading
from PIL import Image, ImageDraw, ImageFont

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --- Imports condicionales ---
HAS_BOARD = False
HAS_ST7789 = False
HAS_PIL = True

try:
    import board
    import busio
    import digitalio
    HAS_BOARD = True
except ImportError:
    HAS_BOARD = False

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# A�adir rutas a drivers/ (hermano de lib/)
_DRIVERS_DIR = os.path.join(os.path.dirname(BASE_DIR), 'drivers')
for _p in [BASE_DIR, _DRIVERS_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)
try:
    from st7789_improved import ST7789
    HAS_ST7789 = True
except ImportError as e:
    print(f"[Display] ST7789 no disponible: {e}")
    HAS_ST7789 = False


class DisplayST7789:
    """Maneja UNA pantalla ST7789 de 2"" (240x320) via SPI.

    Pines segun test_gmt020_dual.py:
      #1: CS=GPIO17, DC=GPIO27, RST=GPIO22
      #2: CS=GPIO24, DC=GPIO25, RST=GPIO23
    """

    PINS = {
        1: {'cs': 17, 'dc': 27, 'rst': 22},
        2: {'cs': 24, 'dc': 25, 'rst': 23},   # CS=GPIO24, RST=GPIO23
    }

    def __init__(self, display_id=1, spi_bus=None):
        self.display_id = display_id
        self.display = None
        self.image = None
        self.draw = None
        self.font = None
        self.font_s = None
        self.W = 240
        self.H = 320
        self.rotation = 1   # 1 = landscape (320x240)
        self.initialized = False
        self.spi_bus = spi_bus
        self._lock = threading.Lock()  # Protege el bus SPI de accesos concurrentes
        self._suspended = False         # Cuando True, todos los dibujos son no-op
        self._init()

    def _init(self):
        if not HAS_ST7789 or not HAS_PIL or not HAS_BOARD:
            print(f"[Display #{self.display_id}] MODULO NO DISPONIBLE")
            return

        pins = self.PINS.get(self.display_id)
        if not pins:
            print(f"[Display #{self.display_id}] ID invalido")
            return

        # Si el GPIO esta ocupado (p.ej. otra app lo reclamo), 
        # la pantalla no estara disponible pero la app sigue funcionando
        try:
            if self.spi_bus is None:
                self.spi_bus = busio.SPI(clock=board.SCK, MOSI=board.MOSI)
                print(f"[SPI] Bus: SCK=GPIO11, MOSI=GPIO10")

            # Retry loop for GPIO assignment (handles "GPIO busy" after parent release)
            max_retries = 3
            last_exc = None
            for attempt in range(1, max_retries + 1):
                try:
                    cs = digitalio.DigitalInOut(getattr(board, f'D{pins["cs"]}'))
                    dc = digitalio.DigitalInOut(getattr(board, f'D{pins["dc"]}'))
                    rst = digitalio.DigitalInOut(getattr(board, f'D{pins["rst"]}'))
                    last_exc = None
                    break
                except Exception as e:
                    last_exc = e
                    err_str = str(e).lower()
                    if 'busy' in err_str or 'gpio' in err_str:
                        print(f"[Display #{self.display_id}] GPIO busy attempt {attempt}/{max_retries}: {e}")
                        if attempt < max_retries:
                            time.sleep(0.5)
                    else:
                        # Non-busy error, don't retry
                        break
            if last_exc:
                raise last_exc

            self.display = ST7789(
                self.spi_bus, cs, dc, rst,
                width=self.W, height=self.H,
                rotation=self.rotation, baudrate=40000000,
                display_name='2.0"', bgr=False, invert=True,
            )
            # After rotation, ST7789 swaps width/height if landscape
            self.W = self.display.width   # 320 if rotation=1
            self.H = self.display.height  # 240 if rotation=1
            self.display.fill((0, 0, 0))

            self.image = Image.new('RGB', (self.W, self.H), (0, 0, 0))
            self.draw = ImageDraw.Draw(self.image)

            for size, attr in [(14, 'font'), (11, 'font_s')]:
                try:
                    f = ImageFont.truetype(
                        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', size)
                except:
                    try:
                        f = ImageFont.truetype(
                            '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', size)
                    except:
                        f = ImageFont.load_default()
                setattr(self, attr, f)

            self.initialized = True
            print(f"[Display #{self.display_id}] OK "
                  f"({self.W}x{self.H}) "
                  f"CS=GPIO{pins['cs']} DC=GPIO{pins['dc']} RST=GPIO{pins['rst']}")

        except Exception as e:
            print(f"[Display #{self.display_id}] NO DISPONIBLE: {e}")
            # La pantalla no esta disponible pero la app sigue

    def ok(self):
        return self.initialized and self.display is not None

    def suspend(self):
        """Suspende la pantalla: todos los dibujos son ignorados.
        Llamar antes de reproducir video para liberar el bus SPI."""
        with self._lock:
            self._suspended = True
        print(f"[Display #{self.display_id}] SUSPENDIDA (bus SPI libre para video)")

    def resume(self):
        """Reactiva la pantalla despues de que el video termino."""
        with self._lock:
            self._suspended = False
        print(f"[Display #{self.display_id}] REACTIVADA")

    def clear(self):
        with self._lock:
            if self._suspended or not self.ok():
                return
            self.display.fill((0, 0, 0))

    def update(self):
        """Envía la imagen interna a la pantalla. Usar siempre dentro del lock."""
        if self.ok() and self.image:
            self.display.display(self.image)

    def show_image(self, img):
        """Muestra una PIL Image directamente (thread-safe). Usado por el reproductor."""
        with self._lock:
            if self._suspended or not self.ok():
                return
            self.display.display(img)

    # --- VISTAS ---

    def show_files(self, files, selected=0, playing_idx=-1, scroll=0, folder=""):
        with self._lock:
            if self._suspended or not self.ok():
                return
            self.image = Image.new('RGB', (self.W, self.H), (5, 5, 20))
            self.draw = ImageDraw.Draw(self.image)

            title = os.path.basename(folder) or "/"
            self.draw.text((5, 2), title, font=self.font, fill=(0, 200, 255))
            self.draw.line([(0, 20), (self.W, 20)], fill=(40, 40, 60))

            max_items = 10
            visible = files[scroll:scroll + max_items]
            y = 25
            for idx, name, is_playing in visible:
                if idx == selected:
                    color = (255, 255, 255); prefix = "> "
                elif is_playing:
                    color = (0, 255, 100); prefix = "> "
                else:
                    color = (180, 180, 200); prefix = "  "
                self.draw.text((5, y), f"{prefix}{name[:22]}",
                               font=self.font_s, fill=color)
                y += 14

            if not visible:
                self.draw.text((10, 40), "No hay videos", font=self.font,
                               fill=(200, 100, 0))
                self.draw.text((10, 60), "Pon MP4 en movies/",
                               font=self.font_s, fill=(120, 120, 120))

            self.draw.rectangle([(1, 1), (self.W-2, self.H-2)],
                                outline=(0, 100, 150), width=1)
            self.update()

    def show_now_playing(self, filename, pos=0, dur=0, status=">"):
        with self._lock:
            if self._suspended or not self.ok():
                return
            self.image = Image.new('RGB', (self.W, self.H), (0, 0, 0))
            self.draw = ImageDraw.Draw(self.image)

            name = os.path.basename(filename)[:20]
            self.draw.text((5, 5), f"{status} {name}", font=self.font,
                           fill=(0, 255, 120))

            if dur > 0:
                prog = min(pos / dur, 1.0)
                bw = self.W - 14; bx, by = 7, 30
                self.draw.rectangle([(bx, by), (bx+bw, by+8)], outline=(60, 60, 80))
                if prog > 0:
                    self.draw.rectangle([(bx, by), (bx+int(bw*prog), by+8)],
                                        fill=(0, 200, 255))

            pt = f"{int(pos//60):02d}:{int(pos%60):02d}"
            dt = f"{int(dur//60):02d}:{int(dur%60):02d}"
            self.draw.text((7, 44), f"{pt} / {dt}", font=self.font_s,
                           fill=(200, 200, 200))

            for i, t in enumerate(["A=Play/Pausa  B=Volver",
                                   "X=Vol-  Y=Vol+", "LB/RB=15s"]):
                self.draw.text((7, 65+i*14), t, font=self.font_s,
                               fill=(100, 100, 120))

            self.draw.rectangle([(1, 1), (self.W-2, self.H-2)],
                                outline=(0, 150, 80), width=1)
            self.update()

    def show_message(self, text, line=0, color=(255, 255, 255)):
        with self._lock:
            if self._suspended or not self.ok():
                return
            self.image = Image.new('RGB', (self.W, self.H), (0, 0, 0))
            self.draw = ImageDraw.Draw(self.image)
            self.draw.text((5, line), text, font=self.font, fill=color)
            self.update()


class DualDisplay:
    """Gestiona DOS pantallas ST7789.

    #1 (GPIO17) - info principal (navegador o reproduccion)
    #2 (GPIO23) - secundaria (portada)
    """

    def __init__(self):
        self.display1 = None
        self.display2 = None
        self.initialized = False
        self._init_dual()

    def _init_dual(self):
        print("[Dual] Inicializando 2 pantallas ST7789...")
        if not HAS_BOARD:
            print("[Dual] board/busio no disponible. Sin pantallas.")
            return
        try:
            spi = busio.SPI(clock=board.SCK, MOSI=board.MOSI)
        except Exception as e:
            print(f"[Dual] Error bus SPI: {e}")
            return

        self.display1 = DisplayST7789(display_id=1, spi_bus=spi)
        self.display2 = DisplayST7789(display_id=2, spi_bus=spi)

        if self.display1.ok() or self.display2.ok():
            self.initialized = True
            print(f"[Dual] #1={'SI' if self.display1.ok() else 'NO'} "
                  f"#2={'SI' if self.display2.ok() else 'NO'}")
        else:
            print("[Dual] Ninguna pantalla disponible")

    def get_main(self):
        if self.display1 and self.display1.ok():
            return self.display1
        return self.display2

    def get_secondary(self):
        if self.display2 and self.display2.ok():
            return self.display2
        return None

    def ok(self):
        return self.initialized

    def clear_all(self):
        if self.display1: self.display1.clear()
        if self.display2: self.display2.clear()

    def show_browser(self, files, selected=0, playing_idx=-1, scroll=0, folder=""):
        d = self.get_main()
        if d: d.show_files(files, selected, playing_idx, scroll, folder)

    def show_playing(self, filename, pos=0, dur=0, status=">"):
        d = self.get_main()
        if d: d.show_now_playing(filename, pos, dur, status)

    def show_cover(self, msg="Reproduciendo..."):
        d = self.get_secondary()
        if d: d.show_message(msg, line=80, color=(0, 200, 255))
