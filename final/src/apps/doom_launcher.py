#!/usr/bin/env python3
"""
doom_launcher.py - CHOCOLATE DOOM (FRAMEBUFFER EDITION)
========================================================
Doom corre en Display #1 (320x240 izquierda).
Display #2 (derecha) muestra logo estatico de DOOM.

Ya NO necesita tocar SPI directamente. Los frames se envian al daemon
fb_daemon.py via socket Unix.

Hardware:
  - Mando Xbox Bluetooth
  - Botones fisicos GPIO
  - fb_daemon.py manejando los ST7789

Uso:
  cd src && sudo python3 apps/doom_launcher.py
"""

import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_BASE_DIR = os.path.dirname(_THIS_DIR)
for _p in [os.path.join(_BASE_DIR, 'lib')]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import time
import subprocess
import threading
import glob
import board
import digitalio
from fb_display import FbDisplay, daemon_available

try:
    import mss
except ImportError:
    print("ERROR: 'mss' no encontrado. Instala con: sudo pip3 install mss")
    mss = None

try:
    from vp_controller import XboxController
except ImportError:
    XboxController = None


class DoomApp:
    def __init__(self):
        print("=" * 45)
        print("  CHOCOLATE DOOM (FB Edition)")
        print("=" * 45)

        self.fb = FbDisplay(3)  # BOTH canvas 640x240
        if not daemon_available():
            print("[Doom] ADVERTENCIA: fb_daemon no detectado!")

        self.controller = XboxController()
        self.running = False
        self.doom_process = None
        self.xvfb_process = None
        self.game_running = False

        # GPIO buttons
        BTN_MAP = {
            'UP': board.D13, 'DOWN': board.D26,
            'ENTER': board.D12, 'BACK': board.D16,
        }
        self.gpio_buttons = {}
        self.btn_prev = {}
        for name, pin in BTN_MAP.items():
            try:
                btn = None
                for _retry in range(5):
                    try:
                        btn = digitalio.DigitalInOut(pin)
                        break
                    except Exception:
                        time.sleep(0.1)
                else:
                    print('[Btn] GPIO busy after retries')
                if btn:
                    btn.direction = digitalio.Direction.INPUT
                    btn.pull = digitalio.Pull.DOWN
                    self.gpio_buttons[name] = btn
                    self.btn_prev[name] = False
            except Exception as e:
                print(f"[Btn {name}] Error: {e}")

        self.wads = self._find_wads()
        self.selected_wad_idx = 0

    def _release_inputs(self):
        for btn in self.gpio_buttons.values():
            try: btn.deinit()
            except: pass
        self.gpio_buttons = {}
        self.btn_prev = {}
        if self.controller:
            try: self.controller.stop()
            except: pass

    def _find_wads(self):
        wads = glob.glob("*.wad") + glob.glob("*.WAD") + glob.glob("wads/*.wad") + glob.glob("wads/*.WAD")
        wads = sorted(list(set(wads)))
        if not wads:
            wads = ["Autodetectar WAD del sistema"]
        return wads

    # ── DRAWING (640x240 canvas) ──

    def _draw_menu(self):
        """Menu de seleccion de WAD."""
        self.fb.blank()
        draw = self.fb.draw()
        BG = (0, 0, 8)
        DIV = (80, 80, 80)
        draw.rectangle([(0, 0), (640, 240)], fill=BG)
        draw.line([(319, 0), (319, 239)], fill=DIV, width=2)

        # ── Left: WAD selector ──
        draw.text((8, 5), "CHOCOLATE DOOM", font=self.fb.font_title, fill=(255, 50, 50))
        draw.text((8, 40), "Selecciona WAD:", font=self.fb.font, fill=(200, 200, 200))

        y = 65
        for i, wad in enumerate(self.wads):
            color = (0, 255, 100) if i == self.selected_wad_idx else (100, 100, 100)
            prefix = "> " if i == self.selected_wad_idx else "  "
            name = os.path.basename(wad)[:20]
            draw.text((8, y), f"{prefix}{name}", font=self.fb.font, fill=color)
            y += 22
            if y > 220:
                break

        draw.text((8, 225), "A=Jugar  B=Salir  ^v=WAD",
                  font=self.fb.font_s, fill=(100, 150, 255))

        # ── Right: DOOM logo ──
        ox = 321
        draw.text((ox + 60, 85), "DOOM", font=self.fb.font_big, fill=(255, 0, 0))
        draw.text((ox + 55, 135), "SPI Edition", font=self.fb.font, fill=(100, 100, 100))
        draw.text((ox + 35, 160), "Display #1 para juego", font=self.fb.font_s, fill=(80, 80, 100))

        self.fb.update()

    def _draw_game_frame(self, doom_img):
        """Dibuja un frame de Doom en la mitad izquierda del canvas.
        doom_img: PIL Image 320x240 RGB (capturada de Xvfb)."""
        self.fb.blank()
        draw = self.fb.draw()

        # ── Left half: paste Doom frame ──
        if doom_img and doom_img.size == (320, 240):
            self.fb.image().paste(doom_img, (0, 0))

        # ── Right half: DOOM logo (static during gameplay) ──
        ox = 321
        draw.rectangle([(320, 0), (639, 239)], fill=(0, 0, 0))
        draw.text((ox + 60, 85), "DOOM", font=self.fb.font_big, fill=(255, 0, 0))
        draw.text((ox + 40, 135), "En juego...", font=self.fb.font, fill=(100, 100, 100))
        draw.line([(319, 0), (319, 239)], fill=(80, 80, 80), width=2)

        self.fb.update()

    # ── GAME LOGIC ──

    def _handle_menu_btn(self, btn):
        if btn in (XboxController.A, 'ENTER'):
            self.start_game()
        elif btn in (XboxController.B, 'BACK'):
            self.running = False
        elif btn in (XboxController.DPAD_U, 300, 'UP'):
            self.selected_wad_idx = max(0, self.selected_wad_idx - 1)
            self._draw_menu()
        elif btn in (XboxController.DPAD_D, 301, 'DOWN'):
            self.selected_wad_idx = min(len(self.wads) - 1, self.selected_wad_idx + 1)
            self._draw_menu()

    def start_game(self):
        if not mss:
            print("[Error] 'mss' no disponible.")
            return

        print("[Doom] Iniciando Xvfb...")
        self.xvfb_process = subprocess.Popen(
            ["Xvfb", ":99", "-screen", "0", "320x240x24", "-nolisten", "tcp"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        time.sleep(1)

        print("[Doom] Iniciando Chocolate Doom...")
        env = os.environ.copy()
        env["DISPLAY"] = ":99"

        cmd = ["chocolate-doom", "-window", "-geometry", "320x240"]
        selected_wad = self.wads[self.selected_wad_idx]
        if selected_wad != "Autodetectar WAD del sistema":
            cmd.extend(["-iwad", selected_wad])

        self.doom_process = subprocess.Popen(
            cmd, env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        self.game_running = True
        self.capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.capture_thread.start()

    def stop_game(self):
        self.game_running = False
        if self.capture_thread and self.capture_thread.is_alive():
            self.capture_thread.join(timeout=1.0)

        if self.doom_process:
            try: self.doom_process.terminate()
            except: pass
            self.doom_process = None

        if self.xvfb_process:
            try: self.xvfb_process.terminate()
            except: pass
            self.xvfb_process = None

        self.wads = self._find_wads()
        self.selected_wad_idx = min(self.selected_wad_idx, max(0, len(self.wads) - 1))
        self._draw_menu()

    def _capture_loop(self):
        """Captura frames de Xvfb y los envia al daemon.
        Doom en Xvfb renderiza a 320x240. Lo capturamos y lo metemos
        en la mitad izquierda del canvas 640x240."""
        os.environ["DISPLAY"] = ":99"

        from PIL import Image
        import numpy as np

        with mss.mss() as sct:
            monitor = sct.monitors[1]

            while self.game_running:
                try:
                    sct_img = sct.grab(monitor)
                    # mss returns BGRA → convert to RGB PIL Image
                    img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")

                    # Draw to framebuffer
                    self._draw_game_frame(img)

                except Exception as e:
                    print(f"[Capture Error] {e}")
                    time.sleep(0.1)

    def run(self):
        self._draw_menu()

        if self.controller.connect():
            self.controller.start()
            print("[Doom] Mando Xbox conectado")

        self.running = True
        print("[Doom] Menu listo.")

        while self.running:
            if not self.game_running:
                # Menu input
                evt = self.controller.get_event(0.01)
                while evt:
                    if evt[0] == 'btn':
                        self._handle_menu_btn(evt[1])
                    evt = self.controller.get_event(0.01)

                # GPIO buttons
                for name, btn in self.gpio_buttons.items():
                    try:
                        current = btn.value
                    except:
                        current = False
                    if current and not self.btn_prev.get(name, False):
                        self.btn_prev[name] = True
                        self._handle_menu_btn(name)
                    self.btn_prev[name] = current

                time.sleep(0.05)
            else:
                # Game running - check if Doom exited
                if self.doom_process and self.doom_process.poll() is not None:
                    print("[Doom] Chocolate Doom termino.")
                    self.stop_game()
                time.sleep(0.5)

        self.controller.stop()
        self._release_inputs()
        self.fb.close()
        print("[Doom] Fin.")


if __name__ == '__main__':
    app = DoomApp()
    try:
        app.run()
    except KeyboardInterrupt:
        print("\n[Doom] Interrumpido.")
        app.stop_game()
        app._release_inputs()
        app.fb.close()
    except Exception as e:
        print(f"\n[Doom] Error fatal: {e}")
        import traceback
        traceback.print_exc()
        app.stop_game()
        app._release_inputs()
        app.fb.close()
