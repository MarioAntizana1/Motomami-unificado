#!/usr/bin/env python3
"""
doom_app.py - Crispy/Chocolate DOOM para MotoMami, pantalla completa HDMI.
Xvfb 640x400 capturado con mss y mostrado en el canvas 640x400.
"""
import os
import sys
import time
import subprocess
import threading
import glob
from PIL import Image, ImageDraw

_SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from libs.fb_display import FbDisplay, _find_font

try:
    import mss
    _HAS_MSS = True
except ImportError:
    _HAS_MSS = False

DOOM_W = 640
DOOM_H = 400


class DoomApp:
    def __init__(self, input_mgr, state=None):
        self._input = input_mgr
        self._state = state
        self._fb = FbDisplay(3)
        self._running = False
        self.doom_process = None
        self.xvfb_process = None
        self.game_running = False
        self.capture_thread = None
        self.last_frame = None
        self._fps_count = 0
        self._fps_t0 = 0.0

        self.wads = self._find_wads()
        self.selected_wad_idx = 0

    def _find_wads(self):
        paths = [
            "/home/motomami/moto/*.wad",
            "/home/motomami/moto/*.WAD",
            "/home/motomami/moto/wads/*.wad",
            "/home/motomami/moto/wads/*.WAD",
            "/home/motomami/final/src/apps/wads/*.wad",
            "/home/motomami/final/src/apps/wads/*.WAD",
        ]
        wads = []
        for p in paths:
            wads.extend(glob.glob(p))
        wads = sorted(list(set(wads)))
        if not wads:
            wads = ["Autodetectar WAD del sistema"]
        return wads

    def run(self):
        self._running = True
        self._draw_menu()

        while self._running:
            if not self.game_running:
                evt = self._input.get_event(timeout=0.1)
                if evt:
                    action, _ = evt
                    if action == "BACK":
                        self._running = False
                    elif action == "UP":
                        self.selected_wad_idx = max(0, self.selected_wad_idx - 1)
                        self._draw_menu()
                    elif action == "DOWN":
                        self.selected_wad_idx = min(len(self.wads) - 1, self.selected_wad_idx + 1)
                        self._draw_menu()
                    elif action == "ENTER":
                        self.start_game()
            else:
                if self.last_frame:
                    self._draw_game_frame(self.last_frame)
                    self.last_frame = None

                if self.doom_process and self.doom_process.poll() is not None:
                    self.stop_game()

                evt = self._input.get_event(timeout=0.03)
                if evt:
                    action, _ = evt
                    if action == "BACK":
                        self.stop_game()

        self._fb.blank()
        self._fb.update()

    def _find_doom_binary(self):
        candidates = ["crispy-doom", "chocolate-doom", "chocolate-doom3", "doom"]
        for c in candidates:
            try:
                r = subprocess.run(["which", c], capture_output=True, text=True, timeout=2)
                if r.returncode == 0 and r.stdout.strip():
                    return r.stdout.strip()
            except Exception:
                pass
        return "crispy-doom"

    def start_game(self):
        if not _HAS_MSS:
            self._render_error("Instale 'mss': sudo pip3 install mss")
            return

        doom_bin = self._find_doom_binary()

        try:
            self.xvfb_process = subprocess.Popen(
                ["Xvfb", ":99", "-screen", "0", f"{DOOM_W}x{DOOM_H}x24", "-nolisten", "tcp"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            time.sleep(0.8)

            env = os.environ.copy()
            env["DISPLAY"] = ":99"

            cmd = [doom_bin, "-width", str(DOOM_W), "-height", str(DOOM_H)]
            selected_wad = self.wads[self.selected_wad_idx]
            if selected_wad != "Autodetectar WAD del sistema":
                cmd.extend(["-iwad", selected_wad])

            self.doom_process = subprocess.Popen(
                cmd, env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            self._render_error(f"No se encontro: {doom_bin}")
            self.stop_game()
            return
        except Exception as e:
            self._render_error(f"Error al iniciar Doom: {e}")
            self.stop_game()
            return

        self.game_running = True
        self.capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.capture_thread.start()

    def stop_game(self):
        self.game_running = False
        if self.capture_thread and self.capture_thread.is_alive():
            self.capture_thread.join(timeout=1.0)

        if self.doom_process:
            try:
                self.doom_process.terminate()
                self.doom_process.wait(timeout=2)
            except Exception:
                try:
                    self.doom_process.kill()
                except Exception:
                    pass
            self.doom_process = None

        if self.xvfb_process:
            try:
                self.xvfb_process.terminate()
                self.xvfb_process.wait(timeout=2)
            except Exception:
                try:
                    self.xvfb_process.kill()
                except Exception:
                    pass
            self.xvfb_process = None

        self._draw_menu()

    def _capture_loop(self):
        import os as _os
        _os.environ["DISPLAY"] = ":99"
        self._fps_count = 0
        self._fps_t0 = time.time()

        with mss.mss() as sct:
            monitor = {"top": 0, "left": 0, "width": DOOM_W, "height": DOOM_H}
            while self.game_running:
                try:
                    sct_img = sct.grab(monitor)
                    img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                    self.last_frame = img
                    self._fps_count += 1
                except Exception:
                    time.sleep(0.05)

    def _draw_menu(self):
        self._fb.blank()
        d = self._fb.draw()

        d.rectangle([(0, 0), (639, 399)], fill=(8, 0, 0))

        d.rectangle([(0, 0), (639, 50)], fill=(60, 0, 0))
        d.text((20, 10), "CHOCOLATE DOOM", font=_find_font(24), fill=(255, 50, 50))

        d.text((20, 70), "Selecciona WAD:", font=_find_font(14), fill=(200, 200, 200))

        y = 100
        for i, wad in enumerate(self.wads):
            color = (0, 255, 100) if i == self.selected_wad_idx else (140, 140, 140)
            prefix = "> " if i == self.selected_wad_idx else "  "
            name = os.path.basename(wad)[:35]
            font = _find_font(13)
            d.text((30, y), f"{prefix}{name}", font=font, fill=color)
            y += 26
            if y > 350:
                break

        d.text((20, 370), "ENTER=Jugar  BACK=Salir  UP/DOWN=WAD",
               font=_find_font(11), fill=(150, 100, 100))

        self._fb.update()

    def _draw_game_frame(self, doom_img):
        self._fb.blank()
        if doom_img:
            if doom_img.size != (DOOM_W, DOOM_H):
                doom_img = doom_img.resize((DOOM_W, DOOM_H))
            self._fb.image().paste(doom_img, (0, 0))

        d = self._fb.draw()
        t = time.time()
        if t - self._fps_t0 >= 2.0 and self._fps_count > 0:
            fps = self._fps_count / (t - self._fps_t0)
            self._fps_count = 0
            self._fps_t0 = t
        else:
            fps = 0
        bar = f"FPS:{fps:.0f}" if fps > 0 else "BACK=Salir"
        d.text((8, DOOM_H - 14), bar, font=_find_font(11), fill=(180, 180, 200))

        self._fb.update()

    def _render_error(self, text):
        self._fb.blank()
        d = self._fb.draw()
        d.text((20, 50), text, font=_find_font(14), fill=(255, 0, 0))
        d.text((20, 250), "Presione ENTER o BACK para volver",
               font=_find_font(11), fill=(150, 150, 150))
        self._fb.update()

        waiting = True
        while waiting:
            evt = self._input.get_event(timeout=0.1)
            if evt:
                action, _ = evt
                if action in ("ENTER", "BACK"):
                    waiting = False
