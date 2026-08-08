#!/usr/bin/env python3
"""
doom_app.py - Crispy Doom launcher directo al framebuffer HDMI.
Sin Xvfb ni capturas: SDL2/KMSDRM renderiza directo.
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

from libs.fb_display import FbDisplay, _find_font, _release_hdmi, _reopen_hdmi


class DoomApp:
    def __init__(self, input_mgr, state=None):
        self._input = input_mgr
        self._state = state
        self._fb = FbDisplay(3)
        self._running = False
        self._doom = None
        self._game_running = False

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
            if not self._game_running:
                evt = self._input.get_event(timeout=0.1)
                if evt:
                    action, _ = evt
                    if action == "BACK":
                        self._running = False
                    elif action == "UP":
                        self.selected_wad_idx = max(0, self.selected_wad_idx - 1)
                        self._draw_menu()
                    elif action == "DOWN":
                        self.selected_wad_idx = min(len(self.wads) - 1,
                                                     self.selected_wad_idx + 1)
                        self._draw_menu()
                    elif action == "ENTER":
                        self._launch_doom()
            else:
                if self._doom and self._doom.poll() is not None:
                    self._doom = None
                    self._game_running = False
                    _reopen_hdmi()
                    self._fb.blank()
                    self._fb.update()
                    self._draw_menu()
                else:
                    evt = self._input.get_event(timeout=0.05)
                    if evt:
                        action, _ = evt
                        if action == "BACK":
                            self._kill_doom()

        if self._doom:
            self._kill_doom()

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
        # Fallback a rutas absolutas (el PATH del servicio no incluye /usr/games)
        for p in ["/usr/games/crispy-doom", "/usr/bin/crispy-doom",
                   "/usr/local/bin/crispy-doom",
                   "/usr/games/chocolate-doom", "/usr/bin/chocolate-doom",
                   "/usr/local/bin/chocolate-doom", "/usr/games/doom"]:
            if os.path.exists(p):
                return p
        return "crispy-doom"

    def _launch_doom(self):
        doom_bin = self._find_doom_binary()

        # Liberar el framebuffer HDMI para que SDL2/KMSDRM lo use
        _release_hdmi()

        env = os.environ.copy()
        env["SDL_VIDEODRIVER"] = "kmsdrm"
        env["SDL_AUDIODRIVER"] = "alsa"

        cmd = [doom_bin]
        selected_wad = self.wads[self.selected_wad_idx]
        if selected_wad != "Autodetectar WAD del sistema":
            cmd.extend(["-iwad", selected_wad])

        try:
            self._doom = subprocess.Popen(
                cmd, env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            self._game_running = True
        except FileNotFoundError:
            self._render_error(f"No se encontro: {doom_bin}")
            _reopen_hdmi()
            return
        except Exception as e:
            self._render_error(f"Error: {e}")
            _reopen_hdmi()
            return

    def _kill_doom(self):
        if self._doom:
            try:
                self._doom.terminate()
                self._doom.wait(timeout=2)
            except Exception:
                try:
                    self._doom.kill()
                except Exception:
                    pass
            self._doom = None
        self._game_running = False
        _reopen_hdmi()
        self._fb.blank()
        self._fb.update()

    def _draw_menu(self):
        self._fb.blank()
        d = self._fb.draw()

        d.rectangle([(0, 0), (639, 399)], fill=(10, 0, 0))
        d.rectangle([(0, 0), (639, 50)], fill=(60, 0, 0))
        d.text((20, 8), "CRISPY DOOM", font=_find_font(26), fill=(255, 50, 50))
        d.text((280, 12), "SDL2 KMS/DRM directo", font=_find_font(11), fill=(150, 80, 80))

        d.text((20, 70), "Selecciona WAD:", font=_find_font(14), fill=(200, 200, 200))

        y = 100
        for i, wad in enumerate(self.wads):
            color = (0, 255, 100) if i == self.selected_wad_idx else (140, 140, 140)
            prefix = "> " if i == self.selected_wad_idx else "  "
            name = os.path.basename(wad)[:35]
            d.text((30, y), f"{prefix}{name}", font=_find_font(13), fill=color)
            y += 26
            if y > 350:
                break

        d.text((20, 372), "ENTER=Jugar  BACK=Salir  UP/DOWN=WAD",
               font=_find_font(11), fill=(150, 100, 100))

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
