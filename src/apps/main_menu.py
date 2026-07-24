import os
import sys
import time

_SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in [_SRC, os.path.join(_SRC, 'libs'), os.path.join(_SRC, 'core')]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from PIL import Image, ImageDraw, ImageFont
from libs.fb_display import FbDisplay, _find_font

VISIBLE = 6

APPS = [
    {"name": "GPS + Mapa",     "key": "gps",     "color": (100, 255, 100), "icon": "G", "desc": "Navegacion GPS con mapa OSM"},
    {"name": "Reproductor",    "key": "music",   "color": (200, 100, 255), "icon": "M", "desc": "Reproductor de musica"},
    {"name": "Video",          "key": "video",   "color": (255, 200,  50), "icon": "V", "desc": "Reproducir videos"},
    {"name": "Camara Vivo",    "key": "camera",  "color": (255, 100, 100), "icon": "C", "desc": "Camara en vivo"},
    {"name": "Doom",           "key": "doom",    "color": (255,  50,  50), "icon": "D", "desc": "Chocolate Doom"},
    {"name": "GPS Diagnostico","key": "gps_diag","color": (  0, 255,  80), "icon": "T", "desc": "Test de GPS y antena"},
    {"name": "Conexiones",     "key": "conex",   "color": ( 80, 180, 255), "icon": "N", "desc": "USB, WiFi, Bluetooth"},
    {"name": "Bluetooth",      "key": "bt_mgr",  "color": (180,  80, 255), "icon": "B", "desc": "Gestionar dispositivos BT"},
    {"name": "Telemetria",     "key": "telem",   "color": ( 50, 200, 255), "icon": "S", "desc": "Datos de telemetria"},
    {"name": "Monitor MQTT",   "key": "mqtt",    "color": (  0, 200, 255), "icon": "Q", "desc": "ESP32 velocidad + luces"},
    {"name": "SALIR",          "key": "exit",    "color": (150, 150, 150), "icon": "X", "desc": "Reiniciar el sistema"},
]


class MainMenu:
    def __init__(self, input_mgr, state=None):
        self._input = input_mgr
        self._state = state
        self._idx = 0
        self._scroll = 0
        self._fb = FbDisplay(3)

        self._f_icon = _find_font(22)
        self._ft = _find_font(16)
        self._fi = _find_font(14)
        self._fs = _find_font(11)
        self._fb_num = _find_font(60)
        self._fb_desc = _find_font(13)

    def run(self) -> str:
        self._draw()
        while True:
            evt = self._input.get_event(timeout=0.05)
            if evt:
                action, _ = evt
                if action in ("UP", "LEFT"):
                    self._idx = max(0, self._idx - 1)
                    self._clamp_scroll()
                    self._draw()
                elif action in ("DOWN", "RIGHT"):
                    self._idx = min(len(APPS) - 1, self._idx + 1)
                    self._clamp_scroll()
                    self._draw()
                elif action == "ENTER":
                    return APPS[self._idx]["key"]
                elif action == "BACK":
                    self._idx = len(APPS) - 1
                    return APPS[self._idx]["key"]

    def _clamp_scroll(self):
        total = len(APPS)
        if self._idx < self._scroll:
            self._scroll = self._idx
        elif self._idx >= self._scroll + VISIBLE:
            self._scroll = self._idx - VISIBLE + 1
        self._scroll = max(0, min(self._scroll, total - VISIBLE))

    def _draw(self):
        self._fb.blank()
        d = self._fb.draw()
        self._draw_list(d)
        self._draw_detail(d)
        self._fb.update()

    def _draw_list(self, d):
        W, H = 320, 240
        ox = 320

        d.rectangle([(ox, 0), (ox + W - 1, 26)], fill=(20, 20, 80))
        d.text((ox + 8, 4), "MOTO MAMI", font=self._ft, fill=(255, 255, 255))
        d.line([(ox, 27), (ox + W - 1, 27)], fill=(60, 60, 120))

        total = len(APPS)
        end = min(self._scroll + VISIBLE, total)
        row_h = 33
        list_h = row_h * (end - self._scroll)
        start_y = 30 + (H - 30 - list_h) // 2

        for i in range(self._scroll, end):
            app = APPS[i]
            sel = i == self._idx
            y = start_y + (i - self._scroll) * row_h

            if sel:
                d.rectangle([(ox + 2, y - 1), (ox + W - 3, y + row_h - 2)], fill=(30, 30, 70), outline=app["color"])

            cx, cy = ox + 18, y + 12
            d.ellipse([(cx - 10, cy - 10), (cx + 10, cy + 10)], fill=app["color"] if sel else (40, 40, 50))
            d.text((cx - 7, cy - 8), app["icon"], font=self._fi, fill=(0, 0, 0) if sel else app["color"])

            name_color = app["color"] if sel else (160, 170, 190)
            d.text((ox + 34, y + 5), app["name"], font=self._fi, fill=name_color)

        if total > VISIBLE:
            bar_h = max(10, int(VISIBLE / total * (H - 50)))
            bar_y = 30 + (self._scroll / (total - VISIBLE)) * (H - 50 - bar_h)
            d.rectangle([(ox + W - 4, int(bar_y)), (ox + W - 2, int(bar_y + bar_h))], fill=(100, 120, 160))

        d.line([(ox, H - 14), (ox + W - 1, H - 14)], fill=(40, 40, 60))
        d.text((ox + 4, H - 12), "^v=Navegar  ENTER=Abrir  B=Salir", font=self._fs, fill=(70, 70, 90))

    def _draw_detail(self, d):
        W, H = 320, 240
        app = APPS[self._idx]

        d.rectangle([(0, 0), (W - 1, H - 1)], fill=(8, 8, 16))

        d.rectangle([(4, 4), (W - 5, 38)], fill=app["color"])
        d.text((12, 8), app["name"], font=self._ft, fill=(0, 0, 0))

        cx, cy = W // 2, 68
        d.ellipse([(cx - 28, cy - 28), (cx + 28, cy + 28)], fill=(15, 15, 25), outline=app["color"], width=3)
        d.text((cx - 14, cy - 16), app["icon"], font=_find_font(36), fill=app["color"])

        d.text((W // 2 - 80, 118), app["desc"], font=self._fb_desc, fill=(170, 180, 200))

        num = str(self._idx + 1)
        d.text((W // 2 - 15, 150), num, font=self._fb_num, fill=app["color"])

        d.rectangle([(4, 190), (W - 5, 215)], outline=(40, 40, 50))
        d.text((W // 2 - 55, 195), "ENTER para lanzar", font=self._fs, fill=(120, 130, 150))

        if self._state:
            music = self._state.get_music()
            if music.is_playing:
                m_name = os.path.basename(music.current_file)[:18] if music.current_file else ""
                d.rectangle([(4, H - 18), (W - 5, H - 4)], fill=(20, 10, 30))
                d.text((8, H - 17), f"\u266B {m_name}", font=self._fs, fill=(180, 80, 255))
