#!/usr/bin/env python3
"""
main_menu.py - Menú principal de MotoMami (framebuffer nativo).
Recibe InputManager ya iniciado y dibuja el menú en las pantallas.
"""
import os
import sys
import time

_SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in [_SRC, os.path.join(_SRC, 'libs'), os.path.join(_SRC, 'core')]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from PIL import Image, ImageDraw, ImageFont
from libs.fb_display import FbDisplay, _find_font

APPS = [
    {"name": "GPS + Mapa",     "key": "gps",     "color": (100, 255, 100)},
    {"name": "Reproductor",    "key": "music",   "color": (200, 100, 255)},
    {"name": "Video",          "key": "video",   "color": (255, 200,  50)},
    {"name": "Camara Vivo",    "key": "camera",  "color": (255, 100, 100)},
    {"name": "Doom",           "key": "doom",    "color": (255,  50,  50)},
    {"name": "Telemetria",     "key": "telem",   "color": ( 50, 200, 255)},
    {"name": "SALIR",          "key": "exit",    "color": (150, 150, 150)},
]


class MainMenu:
    """
    Menú principal. Devuelve la key de la app seleccionada cuando
    el usuario presiona ENTER, o "exit" si elige salir.
    """

    def __init__(self, input_mgr, state=None):
        self._input = input_mgr
        self._state = state
        self._idx = 0
        self._fb = FbDisplay(3)  # Canvas 640x240

        self._ft = _find_font(18)
        self._fi = _find_font(14)
        self._fs = _find_font(11)
        self._fn = _find_font(50)

    def run(self) -> str:
        """Bloquea hasta que el usuario selecciona una app. Retorna su key."""
        self._draw()
        while True:
            evt = self._input.get_event(timeout=0.05)
            if evt:
                action, _ = evt
                if action == "UP":
                    self._idx = max(0, self._idx - 1)
                    self._draw()
                elif action == "DOWN":
                    self._idx = min(len(APPS) - 1, self._idx + 1)
                    self._draw()
                elif action == "ENTER":
                    return APPS[self._idx]["key"]
                elif action == "BACK":
                    self._idx = len(APPS) - 1  # Seleccionar SALIR
                    return APPS[self._idx]["key"]

    def _draw(self):
        W, H = 320, 240
        self._fb.blank()
        d = self._fb.draw()

        # ── Pantalla 1 (izq): Lista de apps ──
        d.rectangle([(0, 0), (W - 1, 27)], fill=(20, 20, 80))
        d.text((8, 4), "MOTO MAMI", font=self._ft, fill=(255, 255, 255))
        d.line([(0, 27), (W, 27)], fill=(60, 60, 120))

        y = 33
        for i, app in enumerate(APPS):
            selected = (i == self._idx)
            color = app["color"] if selected else (110, 110, 130)
            prefix = "> " if selected else "  "
            if selected:
                d.rectangle([(3, y - 1), (W - 3, y + 22)], fill=(30, 30, 70), outline=app["color"])
            d.text((10, y + 3), f"{prefix}{app['name']}", font=self._fi, fill=color)
            y += 26

        d.line([(0, H - 14), (W, H - 14)], fill=(40, 40, 60))
        d.text((4, H - 12), "^v Nav   ENTER=Lanzar   B=Salir", font=self._fs, fill=(70, 70, 90))

        # ── Pantalla 2 (der): App seleccionada ──
        ox = 320
        app = APPS[self._idx]
        d.rectangle([(ox + 4, 4), (ox + W - 5, H - 5)], outline=app["color"], width=3)
        d.rectangle([(ox + 4, 4), (ox + W - 5, 37)], fill=app["color"])
        d.text((ox + 12, 7), app["name"], font=self._ft, fill=(0, 0, 0))

        # Número grande
        num = str(self._idx + 1)
        d.text((ox + W // 2 - 15, 55), num, font=self._fn, fill=app["color"])

        # Indicador de música si está sonando
        if self._state:
            music = self._state.get_music()
            if music.is_playing:
                m_name = os.path.basename(music.current_file)[:20] if music.current_file else ""
                d.rectangle([(ox + 4, H - 35), (ox + W - 5, H - 5)], fill=(20, 10, 30))
                d.text((ox + 8, H - 32), f"♪ {m_name}", font=self._fs, fill=(180, 80, 255))

        d.text((ox + W // 2 - 90, 165), "Presiona ENTER", font=self._fi, fill=(200, 200, 200))
        d.text((ox + W // 2 - 80, 188), "para lanzar app", font=self._fs, fill=(100, 100, 100))

        self._fb.update()
