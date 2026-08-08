import os
import sys
import time

_SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in [_SRC, os.path.join(_SRC, 'libs'), os.path.join(_SRC, 'core')]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from PIL import Image, ImageDraw
from libs.fb_display import FbDisplay, _find_font

COLS = 3
ROWS = 4

APPS = [
    {"name": "GPS",       "key": "gps",     "color": (100, 255, 100), "icon": "GPS"},
    {"name": "Musica",    "key": "music",   "color": (200, 100, 255), "icon": "MUS"},
    {"name": "Video",     "key": "video",   "color": (255, 200,  50), "icon": "VID"},
    {"name": "Camara",    "key": "camera",  "color": (255, 100, 100), "icon": "CAM"},
    {"name": "Doom",      "key": "doom",    "color": (255,  50,  50), "icon": "DOOM"},
    {"name": "GPS Diag",  "key": "gps_diag","color": (  0, 255,  80), "icon": "DIA"},
    {"name": "Conexiones","key": "conex",   "color": ( 80, 180, 255), "icon": "NET"},
    {"name": "Bluetooth", "key": "bt_mgr",  "color": (180,  80, 255), "icon": "BT"},
    {"name": "Telemetria","key": "telem",   "color": ( 50, 200, 255), "icon": "TLM"},
    {"name": "MQTT",      "key": "mqtt",    "color": (  0, 200, 255), "icon": "MQT"},
    {"name": "Tema",      "key": "theme",   "color": (255, 220, 100), "icon": "TEMA"},
    {"name": "SALIR",     "key": "exit",    "color": (150, 150, 150), "icon": "X"},
]

CELL_W = 200
CELL_H = 90
PAD_X = 13
PAD_Y = 18
GAP_X = 10
GAP_Y = 6
START_X = (640 - (COLS * CELL_W + (COLS - 1) * GAP_X)) // 2
START_Y = (400 - (ROWS * CELL_H + (ROWS - 1) * GAP_Y)) // 2


class MainMenu:
    def __init__(self, input_mgr, state=None):
        self._input = input_mgr
        self._state = state
        self._idx = 0
        self._fb = FbDisplay(3)

        self._f_icon = _find_font(14)
        self._f_name = _find_font(13)
        self._f_small = _find_font(11)
        self._f_title = _find_font(20)

    def _cell_pos(self, idx):
        row = idx // COLS
        col = idx % COLS
        x = START_X + col * (CELL_W + GAP_X)
        y = START_Y + row * (CELL_H + GAP_Y)
        return x, y

    def run(self) -> str:
        self._draw()
        while True:
            evt = self._input.get_event(timeout=0.05)
            if evt:
                action, _ = evt
                if action == "UP":
                    self._idx = max(0, self._idx - COLS)
                    self._draw()
                elif action == "DOWN":
                    self._idx = min(len(APPS) - 1, self._idx + COLS)
                    self._draw()
                elif action == "LEFT":
                    self._idx = max(0, self._idx - 1)
                    self._draw()
                elif action == "RIGHT":
                    self._idx = min(len(APPS) - 1, self._idx + 1)
                    self._draw()
                elif action == "ENTER":
                    key = APPS[self._idx]["key"]
                    if key == "theme":
                        self._draw()
                        continue
                    return key
                elif action == "BACK":
                    return APPS[len(APPS) - 1]["key"]

    def _draw(self):
        self._fb.blank()
        d = self._fb.draw()

        d.rectangle([(0, 0), (639, 31)], fill=(20, 20, 35))
        d.text((16, 4), "MotoMami", font=self._f_title, fill=(255, 255, 255))
        d.text((580, 6), f"{self._idx + 1}/{len(APPS)}", font=self._f_small, fill=(120, 120, 140))

        for i, app in enumerate(APPS):
            x, y = self._cell_pos(i)
            sel = i == self._idx

            if sel:
                d.rounded_rectangle(
                    [(x - 3, y - 3), (x + CELL_W + 2, y + CELL_H + 2)],
                    radius=8, fill=(35, 35, 55), outline=(255, 255, 100), width=2
                )
            else:
                d.rounded_rectangle(
                    [(x, y), (x + CELL_W - 1, y + CELL_H - 1)],
                    radius=6, fill=(15, 15, 28), outline=(40, 40, 55), width=1
                )

            cx, cy = x + CELL_W // 2, y + 32
            r = 18
            fill_color = app["color"] if sel else tuple(max(0, c - 100) for c in app["color"])
            d.ellipse([(cx - r, cy - r), (cx + r, cy + r)], fill=fill_color)
            icon_text = app["icon"]
            if len(icon_text) > 2:
                icon_text = icon_text[:2]
            bb = d.textbbox((0, 0), icon_text, font=self._f_icon)
            tw, th = bb[2] - bb[0], bb[3] - bb[1]
            d.text((cx - tw // 2, cy - th // 2 - 1), icon_text, font=self._f_icon,
                   fill=(255, 255, 255) if sel else (180, 180, 200))

            name = app["name"]
            bb2 = d.textbbox((0, 0), name, font=self._f_name)
            nw = bb2[2] - bb2[0]
            d.text((x + (CELL_W - nw) // 2, y + 62), name, font=self._f_name,
                   fill=(255, 255, 255) if sel else (160, 160, 180))

        self._fb.update()
