#!/usr/bin/env python3
"""
doom_app.py - CHOCOLATE DOOM launcher for MotoMami.
Runs Doom on Display 1 (left) using Xvfb + mss for screen capture.
Display 2 (right) shows static DOOM logo.
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

from libs.fb_display import FbDisplay, _find_font, W, H

try:
    import mss
    _HAS_MSS = True
except ImportError:
    _HAS_MSS = False

class DoomApp:
    def __init__(self, input_mgr, state=None):
        self._input = input_mgr
        self._state = state
        self._fb = FbDisplay(3)  # Dual screen canvas 640x240
        self._running = False
        self.doom_process = None
        self.xvfb_process = None
        self.game_running = False
        self.capture_thread = None
        
        # Buscar wads en /home/motomami/moto/ y /home/motomami/moto/wads/ y /home/motomami/final/src/apps/wads/
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
                # Menú de selección
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
                # Juego ejecutándose, comprobar si terminó el proceso
                if self.doom_process and self.doom_process.poll() is not None:
                    print("[Doom] Chocolate Doom terminó.")
                    self.stop_game()
                
                # O si el usuario presionó BACK para salir
                evt = self._input.get_event(timeout=0.1)
                if evt:
                    action, _ = evt
                    if action == "BACK":
                        print("[Doom] Cancelando por el usuario (BACK).")
                        self.stop_game()

        self._fb.blank()
        self._fb.update()

    def _find_doom_binary(self):
        # crispy-doom preferido: soporta mouselook (mirar arriba/abajo)
        candidates = ["crispy-doom", "chocolate-doom", "chocolate-doom3", "doom"]
        for c in candidates:
            try:
                r = subprocess.run(["which", c], capture_output=True, text=True, timeout=2)
                if r.returncode == 0 and r.stdout.strip():
                    return r.stdout.strip()
            except:
                pass
        for p in ["/usr/games/crispy-doom", "/usr/bin/crispy-doom",
                   "/usr/local/bin/crispy-doom",
                   "/usr/games/chocolate-doom", "/usr/bin/chocolate-doom",
                   "/usr/local/bin/chocolate-doom", "/usr/games/doom"]:
            if os.path.exists(p):
                return p
        return "chocolate-doom"

    def start_game(self):
        if not _HAS_MSS:
            self._render_error("Instale 'mss':\nsudo pip3 install mss")
            return

        doom_bin = self._find_doom_binary()
        print(f"[Doom] Usando binario: {doom_bin}")

        print("[Doom] Lanzando Xvfb...")
        try:
            self.xvfb_process = subprocess.Popen(
                ["Xvfb", ":99", "-screen", "0", "320x240x24", "-nolisten", "tcp"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            time.sleep(1) # Esperar a que Xvfb inicie
            
            print("[Doom] Lanzando Chocolate Doom...")
            env = os.environ.copy()
            env["DISPLAY"] = ":99"
            
            cmd = [doom_bin, "-window", "-geometry", "320x240"]
            selected_wad = self.wads[self.selected_wad_idx]
            if selected_wad != "Autodetectar WAD del sistema":
                cmd.extend(["-iwad", selected_wad])
            
            try:
                self.doom_process = subprocess.Popen(
                    cmd, env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            except FileNotFoundError:
                self._render_error(f"No se encontro:\n{doom_bin}\n\n"
                                   "Instala crispy-doom:\nsudo apt install crispy-doom")
                self.stop_game()
                return

            self.game_running = True
            self.capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
            self.capture_thread.start()
            
        except Exception as e:
            self._render_error(f"Error al iniciar Doom:\n{e}")
            self.stop_game()

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
        os.environ["DISPLAY"] = ":99"
        
        with mss.mss() as sct:
            monitor = sct.monitors[1]
            while self.game_running:
                try:
                    sct_img = sct.grab(monitor)
                    # Convertir de BGRA a RGB
                    img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                    self._draw_game_frame(img)
                except Exception as e:
                    print(f"[Doom Capture] Error: {e}")
                    time.sleep(0.1)

    def _draw_menu(self):
        self._fb.blank()
        draw = self._fb.draw()
        BG = (0, 0, 8)
        DIV = (80, 80, 80)
        draw.rectangle([(0, 0), (640, 240)], fill=BG)
        draw.line([(319, 0), (319, 239)], fill=DIV, width=2)

        # ── Pantalla 1 (Izquierda): Selector de WADs ──
        draw.text((8, 5), "CHOCOLATE DOOM", font=self._fb.font_title, fill=(255, 50, 50))
        draw.text((8, 40), "Selecciona WAD:", font=self._fb.font, fill=(200, 200, 200))

        y = 65
        for i, wad in enumerate(self.wads):
            color = (0, 255, 100) if i == self.selected_wad_idx else (100, 100, 100)
            prefix = "> " if i == self.selected_wad_idx else "  "
            name = os.path.basename(wad)[:20]
            draw.text((8, y), f"{prefix}{name}", font=self._fb.font, fill=color)
            y += 22
            if y > 210:
                break

        draw.text((8, 225), "ENTER=Jugar  BACK=Salir  ^v=WAD", font=self._fb.font_s, fill=(100, 150, 255))

        # ── Pantalla 2 (Derecha): Logo DOOM ──
        ox = 321
        draw.text((ox + 60, 85), "DOOM", font=self._fb.font_big, fill=(255, 0, 0))
        draw.text((ox + 55, 135), "SPI Edition", font=self._fb.font, fill=(100, 100, 100))
        draw.text((ox + 35, 160), "Display #1 para juego", font=self._fb.font_s, fill=(80, 80, 100))

        self._fb.update()

    def _draw_game_frame(self, doom_img):
        self._fb.blank()
        draw = self._fb.draw()

        # Pegar el frame de Doom en la mitad izquierda (Display 1)
        if doom_img:
            if doom_img.size != (320, 240):
                doom_img = doom_img.resize((320, 240))
            self._fb.image().paste(doom_img, (0, 0))

        # Dibujar Display 2 (Derecha) estático durante el juego
        ox = 321
        draw.rectangle([(320, 0), (639, 239)], fill=(0, 0, 0))
        draw.text((ox + 60, 85), "DOOM", font=self._fb.font_big, fill=(255, 0, 0))
        draw.text((ox + 40, 135), "En juego...", font=self._fb.font, fill=(100, 100, 100))
        draw.line([(319, 0), (319, 239)], fill=(80, 80, 80), width=2)

        self._fb.update()

    def _render_error(self, text):
        self._fb.blank()
        draw = self._fb.draw()
        draw.text((20, 50), text, font=self._fb.font, fill=(255, 0, 0))
        draw.text((20, 180), "Presione ENTER o BACK para volver", font=self._fb.font_s, fill=(150, 150, 150))
        self._fb.update()
        
        # Bloquear hasta que el usuario presione ENTER o BACK
        waiting = True
        while waiting:
            evt = self._input.get_event(timeout=0.1)
            if evt:
                action, _ = evt
                if action in ("ENTER", "BACK"):
                    waiting = False
