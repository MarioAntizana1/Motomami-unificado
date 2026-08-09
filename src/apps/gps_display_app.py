#!/usr/bin/env python3
"""
gps_display_app.py - App GPS con mapa y datos de navegación.
Usa SystemState para la posición (con caché de última ubicación).
Pantalla 1: Mapa | Pantalla 2: Datos de velocidad/satélites
"""
import os
import sys
import time
import math
import threading

_SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in [_SRC, os.path.join(_SRC, 'libs'), os.path.join(_SRC, 'core'),
           os.path.join(_SRC, 'drivers')]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from PIL import Image, ImageDraw, ImageFont
from libs.fb_display import FbDisplay, _find_font
from config_loader import MAP_ZOOM, GPS_REFRESH, MAX_ROUTE_PTS, DISPLAY_MODE

try:
    from libs.map_renderer import MapRenderer, cache_stats as _tile_cache_stats
    _HAS_MAP = True
except ImportError:
    _HAS_MAP = False
    _tile_cache_stats = lambda: {"hits": 0, "misses": 0, "downloads": 0}
    print("[GPS App] MapRenderer no disponible")

C_GREEN  = (0, 220, 80)
C_BLUE   = (0, 180, 255)
C_YELLOW = (255, 200, 50)
C_RED    = (255, 60, 60)
C_DIM    = (80, 80, 80)
C_BG     = (0, 0, 0)


class GPSDisplayApp:
    def __init__(self, input_mgr, state=None):
        self._input = input_mgr
        self._state = state
        self._fb = FbDisplay(1, size=(640, 400))
        self._map_fb = None
        self._running = False
        self._route_points = []
        self._zoom = MAP_ZOOM
        self._lock = threading.Lock()
        self._last_cached = False

        if _HAS_MAP:
            map_size = (640, 400) if DISPLAY_MODE == "hdmi" else (320, 240)
            self._map = MapRenderer(width=map_size[0], height=map_size[1], zoom=self._zoom)
        else:
            self._map = None

        self._f_huge   = _find_font(56)
        self._f_big    = _find_font(32)
        self._f_normal = _find_font(14)
        self._f_small  = _find_font(11)

    def run(self):
        self._running = True
        self._last_cached = False
        self._route_points = []
        self._show_splash()
        last_render = 0

        while self._running:
            evt = self._input.get_event(timeout=0.02)
            if evt:
                action, _ = evt
                if action == "BACK":
                    self._running = False
                elif action == "UP":
                    self._zoom = min(18, self._zoom + 1)
                    if self._map:
                        self._map.zoom = self._zoom
                elif action == "DOWN":
                    self._zoom = max(13, self._zoom - 1)
                    if self._map:
                        self._map.zoom = self._zoom

            now = time.time()
            if now - last_render >= GPS_REFRESH:
                self._render()
                last_render = now

        self._fb.blank()
        self._fb.update()

    def _render(self):
        gps = self._state.get_gps() if self._state else None
        has_gps = gps is not None
        has_fix = gps.has_fix if has_gps else False
        has_cache = gps.cached_has_fix if has_gps else False
        no_position = (not has_gps) or (gps.lat == 0 and gps.lon == 0 and not has_cache)

        if no_position:
            img = self._render_no_gps(640, 400)
            self._fb.image().paste(img, (0, 0))
            self._fb.update()
            return

        lat, lon = gps.get_display_coords()
        using_cache = not has_fix and gps.cached_has_fix
        self._last_cached = using_cache

        if has_fix and lat != 0 and lon != 0:
            if not self._route_points or self._dist(
                self._route_points[-1], (lat, lon)
            ) > 0.0001:
                self._route_points.append((lat, lon))
                if len(self._route_points) > MAX_ROUTE_PTS:
                    self._route_points = self._route_points[-MAX_ROUTE_PTS:]

        img_map = self._render_map(gps, lat, lon, using_cache)
        full = self._fb.image()
        full.paste(img_map, (0, 0))

        dire = self._state.get_esp32_direccionales() if self._state else None
        velo = self._state.get_esp32_velocimetro() if self._state else None
        self._draw_hud(full, gps, dire, velo)

        self._fb.update()

    def _draw_hud(self, img, gps, dire, velo):
        d = ImageDraw.Draw(img)
        W, H = 640, 400

        # Barra superior: direccionales + velocidad
        d.rectangle([(0, 0), (W - 1, 32)], fill=(0, 0, 0))
        d.line([(0, 32), (W - 1, 32)], fill=(50, 50, 50))

        unit = _find_font(9)

        # Señal izquierda
        left = bool(dire and dire.intermitente_izq)
        lc = (0, 200, 50) if left else (30, 30, 30)
        lo = (0, 150, 30) if left else (50, 50, 50)
        d.rectangle([(6, 6), (28, 26)], fill=lc, outline=lo)
        d.text((10, 10), "L", font=unit,
               fill=(0, 0, 0) if left else (100, 100, 100))

        # Emergencia
        emerg = bool(dire and dire.emergencia)
        if emerg:
            d.rectangle([(36, 6), (58, 26)], fill=(255, 50, 0), outline=(200, 0, 0))
            d.text((40, 10), "!", font=unit, fill=(255, 255, 255))
        else:
            d.rectangle([(36, 6), (58, 26)], fill=(25, 25, 25), outline=(50, 50, 50))
            d.text((43, 10), "!", font=unit, fill=(80, 80, 80))

        # Luz nocturna
        night = bool(dire and dire.luz_nocturna)
        nf = (0, 100, 255) if night else (25, 25, 25)
        no = (0, 70, 200) if night else (50, 50, 50)
        d.rectangle([(66, 6), (88, 26)], fill=nf, outline=no)
        d.text((70, 10), "N", font=unit,
               fill=(255, 255, 255) if night else (100, 100, 100))

        # Freno
        brake = bool(dire and dire.frenado)
        bf = (255, 0, 0) if brake else (25, 25, 25)
        bo = (200, 0, 0) if brake else (50, 50, 50)
        d.rectangle([(96, 6), (118, 26)], fill=bf, outline=bo)
        d.text((100, 10), "B", font=unit,
               fill=(255, 255, 255) if brake else (100, 100, 100))

        # Velocidad GPS centro
        spd = gps.speed_kmh if gps.has_fix else 0.0
        spd_text = f"{spd:.0f}"
        spd_font = _find_font(26)
        bb = d.textbbox((0, 0), spd_text, font=spd_font)
        tw = bb[2] - bb[0]
        d.text(((W - tw) // 2, 0), spd_text, font=spd_font, fill=(255, 255, 255))
        d.text(((W + tw) // 2 + 2, 18), "km/h", font=unit, fill=(150, 150, 150))

        # Direccional derecha
        right = bool(dire and dire.intermitente_der)
        rc = (0, 200, 50) if right else (30, 30, 30)
        rco = (0, 150, 30) if right else (50, 50, 50)
        d.rectangle([(W - 30, 6), (W - 8, 26)], fill=rc, outline=rco)
        d.text((W - 26, 10), "R", font=unit,
               fill=(0, 0, 0) if right else (100, 100, 100))

        # Velocidad rueda
        wheel = velo.speed if velo is not None else 0.0
        if wheel > 0:
            d.text((W // 2 - 90, 18), f"R:{wheel:.0f}", font=unit, fill=(100, 180, 255))

        # Barra inferior: distancias
        trip_km = gps.gps_trip_distance_m / 1000.0
        total_km = gps.gps_total_distance_m / 1000.0
        odo = velo.odometro if velo is not None else 0.0
        sats = gps.num_satellites

        d.rectangle([(0, H - 18), (W - 1, H - 1)], fill=(0, 0, 0))
        d.line([(0, H - 18), (W - 1, H - 18)], fill=(50, 50, 50))
        status = (f"Trip:{trip_km:.1f}km | Total:{total_km:.1f}km | "
                  f"ODO:{odo:.0f}km | Sats:{sats}")
        d.text((10, H - 16), status, font=unit, fill=(180, 180, 200))

    def _render_map(self, gps, lat, lon, using_cache):
        W, H = 640, 400
        if lat == 0 and lon == 0:
            return self._render_no_gps(W, H)

        if self._map:
            try:
                img = self._map.render_map(lat, lon, self._route_points)
            except Exception:
                img = Image.new("RGB", (W, H), (10, 10, 20))
        else:
            img = Image.new("RGB", (W, H), (10, 10, 20))

        draw = ImageDraw.Draw(img)

        draw.rectangle([0, H - 16, W - 1, H - 1], fill=(0, 0, 0, 180))
        status = (f"GPS:{'OK' if gps.has_fix else 'CACHE'}"
                  f" Sats:{gps.num_satellites}"
                  f" {gps.speed_kmh:.0f}km/h Z:{self._zoom}")
        draw.text((4, H - 14), status, font=self._f_small,
                  fill=C_YELLOW if using_cache else C_GREEN)

        if using_cache:
            draw.rectangle([0, 0, W - 1, 16], fill=(80, 40, 0, 180))
            draw.text((4, 2), "⚠ Última posición conocida", font=self._f_small, fill=C_YELLOW)

        return img

    def _render_no_gps(self, W, H):
        img = Image.new("RGB", (W, H), (10, 10, 20))
        draw = ImageDraw.Draw(img)
        cx, cy = W // 2, H // 2 - 20
        for i in range(4):
            angle = (time.time() * 2 + i * 1.57) % 6.28
            x = cx + int(30 * math.cos(angle))
            y = cy + int(30 * math.sin(angle))
            draw.ellipse([x - 4, y - 4, x + 4, y + 4], fill=C_BLUE)
        text = "BUSCANDO GPS..."
        bb = draw.textbbox((0, 0), text, font=self._f_normal)
        tw = bb[2] - bb[0]
        draw.text(((W - tw) // 2, cy + 45), text, font=self._f_normal, fill=C_YELLOW)
        return img

    def _show_splash(self):
        self._fb.blank()
        d = self._fb.draw()
        d.text((60, 100), "GPS + MAPA", font=_find_font(22), fill=C_BLUE)
        d.text((380, 100), "GPS DATOS", font=_find_font(22), fill=C_GREEN)
        d.text((60, 135), "Iniciando...", font=_find_font(14), fill=(200, 200, 200))
        self._fb.update()
        time.sleep(1)

    @staticmethod
    def _dist(p1, p2):
        return ((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2) ** 0.5
