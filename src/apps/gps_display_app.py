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
from config_loader import MAP_ZOOM, GPS_REFRESH, MAX_ROUTE_PTS

try:
    from libs.map_renderer import MapRenderer, cache_stats as _tile_cache_stats
    _HAS_MAP = True
except ImportError:
    _HAS_MAP = False
    _tile_cache_stats = lambda: {"hits": 0, "misses": 0, "downloads": 0}
    print("[GPS App] MapRenderer no disponible")

# Colores
C_GREEN  = (0, 220, 80)
C_BLUE   = (0, 180, 255)
C_YELLOW = (255, 200, 50)
C_RED    = (255, 60, 60)
C_DIM    = (80, 80, 80)
C_BG     = (0, 0, 0)


class GPSDisplayApp:
    """
    App de GPS/Mapa. Se ejecuta hasta que el usuario presiona BACK.
    Parámetros:
        input_mgr: InputManager (ya iniciado)
        state: SystemState
    """

    def __init__(self, input_mgr, state=None):
        self._input = input_mgr
        self._state = state
        self._fb = FbDisplay(3)  # canvas 640x240
        self._running = False
        self._route_points = []
        self._zoom = MAP_ZOOM
        self._lock = threading.Lock()
        self._last_cached = False  # ¿estamos mostrando posición cacheada?

        if _HAS_MAP:
            self._map = MapRenderer(width=320, height=240, zoom=self._zoom)
        else:
            self._map = None

        # Fuentes
        self._f_huge   = _find_font(56)
        self._f_big    = _find_font(32)
        self._f_normal = _find_font(14)
        self._f_small  = _find_font(11)

    def run(self):
        self._running = True
        self._show_splash()
        last_render = 0

        while self._running:
            # ── Entrada ──
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

            # ── Render cada GPS_REFRESH segundos ──
            now = time.time()
            if now - last_render >= GPS_REFRESH:
                self._render()
                last_render = now

        self._fb.blank()
        self._fb.update()

    def _render(self):
        gps = self._state.get_gps() if self._state else None
        if not gps:
            return

        lat, lon = gps.get_display_coords()
        using_cache = not gps.has_fix and gps.cached_has_fix
        self._last_cached = using_cache

        # Actualizar ruta
        if gps.has_fix and lat != 0 and lon != 0:
            if not self._route_points or self._dist(
                self._route_points[-1], (lat, lon)
            ) > 0.0001:
                self._route_points.append((lat, lon))
                if len(self._route_points) > MAX_ROUTE_PTS:
                    self._route_points = self._route_points[-MAX_ROUTE_PTS:]

        img_map  = self._render_map(gps, lat, lon, using_cache)
        img_data = self._render_data(gps, using_cache)

        full = self._fb.image()
        full.paste(img_map,  (0,   0))
        full.paste(img_data, (320, 0))
        self._fb.update()

    def _render_map(self, gps, lat, lon, using_cache) -> Image.Image:
        W, H = 320, 240
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

        # Barra inferior
        draw.rectangle([0, H - 16, W - 1, H - 1], fill=(0, 0, 0, 180))
        status = (f"GPS:{'OK' if gps.has_fix else 'CACHE'}"
                  f" Sats:{gps.num_satellites}"
                  f" {gps.speed_kmh:.0f}km/h Z:{self._zoom}")
        draw.text((4, H - 14), status, font=self._f_small,
                  fill=C_YELLOW if using_cache else C_GREEN)

        # Indicador de caché
        if using_cache:
            draw.rectangle([0, 0, W - 1, 16], fill=(80, 40, 0, 180))
            draw.text((4, 2), "⚠ Última posición conocida", font=self._f_small, fill=C_YELLOW)

        return img

    def _render_no_gps(self, W: int, H: int) -> Image.Image:
        img = Image.new("RGB", (W, H), (10, 10, 20))
        draw = ImageDraw.Draw(img)
        # Animación circular
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

    def _render_data(self, gps, using_cache) -> Image.Image:
        W, H = 320, 240
        img = Image.new("RGB", (W, H), C_BG)
        draw = ImageDraw.Draw(img)

        has_fix = gps.has_fix

        # ── Barra superior: estado ──
        draw.rectangle([0, 0, W - 1, 20], fill=(20, 20, 30))
        dot = C_GREEN if has_fix else (C_YELLOW if using_cache else C_RED)
        draw.ellipse([6, 6, 14, 14], fill=dot)
        status_txt = "FIX OK" if has_fix else ("CACHE" if using_cache else "SIN FIX")
        draw.text((20, 3), status_txt, font=self._f_normal,
                  fill=C_GREEN if has_fix else (C_YELLOW if using_cache else C_RED))

        if gps.gps_time and len(gps.gps_time) >= 6:
            t = gps.gps_time
            draw.text((W - 90, 3), f"{t[:2]}:{t[2:4]}:{t[4:6]}", font=self._f_small, fill=C_BLUE)

        # ── Velocidad ──
        y = 28
        draw.text((10, y), "VELOCIDAD", font=self._f_small, fill=C_DIM)
        vel_txt = f"{gps.speed_kmh:.1f}"
        vel_col = (255, 255, 255) if has_fix and gps.speed_kmh > 0 else C_DIM
        draw.text((10, y + 8), vel_txt, font=self._f_huge, fill=vel_col)
        bb = draw.textbbox((0, 0), vel_txt, font=self._f_huge)
        draw.text((10 + bb[2] + 5, y + 45), "km/h", font=self._f_normal, fill=C_DIM)

        # ── Altitud ──
        y = 118
        draw.text((10, y), "ALTITUD", font=self._f_small, fill=C_DIM)
        alt_col = C_GREEN if has_fix else C_DIM
        draw.text((10, y + 8), f"{gps.altitude:.0f} m", font=self._f_big, fill=alt_col)

        # ── Divisor ──
        draw.line([(175, 25), (175, H - 55)], fill=(40, 40, 40), width=1)

        # ── Rumbo ──
        rx, ry = 187, 28
        draw.text((rx, ry), "RUMBO", font=self._f_small, fill=C_DIM)
        rumbo_col = C_YELLOW if has_fix else C_DIM
        track = gps.track_angle
        # Flecha
        acx, acy = rx + 30, ry + 35
        ang = math.radians(track - 90)
        ax = acx + int(20 * math.cos(ang))
        ay = acy + int(20 * math.sin(ang))
        draw.line([(acx, acy), (ax, ay)], fill=rumbo_col, width=4)
        for da in (2.5, -2.5):
            tx = ax + int(7 * math.cos(ang + da))
            ty = ay + int(7 * math.sin(ang + da))
            draw.polygon([(ax, ay), (tx, ty), (ax + int(2*math.cos(ang-da)), ay + int(2*math.sin(ang-da)))], fill=rumbo_col)
        draw.text((rx + 60, ry + 20), f"{track:.0f}°", font=self._f_big, fill=rumbo_col)

        # ── Satélites ──
        y = 95
        draw.text((rx, y), "SATELITES", font=self._f_small, fill=C_DIM)
        sats_col = C_GREEN if gps.num_satellites >= 4 else C_YELLOW
        draw.text((rx, y + 14), str(gps.num_satellites), font=self._f_big, fill=sats_col)

        # ── Barra inferior: sistema + caché tiles ──
        yb = H - 50
        draw.rectangle([0, yb, W - 1, H - 1], fill=(15, 15, 20))
        cs = _tile_cache_stats()
        cache_pct = (cs["hits"] / (cs["hits"] + cs["misses"]) * 100) if (cs["hits"] + cs["misses"]) > 0 else 100
        draw.text((10, yb + 4), f"CACHE {cache_pct:.0f}% ({cs['hits']}) DL:{cs['downloads']}", font=self._f_small, fill=C_GREEN if cache_pct > 80 else C_YELLOW)
        if self._state:
            m = self._state.get_metrics()
            cpu, ram, temp = m.cpu_percent, m.ram_percent, m.cpu_temp
            cpu_c = C_GREEN if cpu < 50 else (C_YELLOW if cpu < 80 else C_RED)
            draw.text((10, yb + 18), f"CPU", font=self._f_small, fill=cpu_c)
            draw.rectangle([40, yb + 19, 100, yb + 27], fill=(30, 30, 30))
            draw.rectangle([40, yb + 19, 40 + int(60 * cpu / 100), yb + 27], fill=cpu_c)
            draw.text((105, yb + 18), f"{cpu:.0f}%", font=self._f_small, fill=cpu_c)
            draw.text((145, yb + 18), f"RAM {ram:.0f}%", font=self._f_small, fill=C_BLUE)
            if temp > 0:
                tc = C_GREEN if temp < 55 else (C_YELLOW if temp < 70 else C_RED)
                draw.text((10, yb + 32), f"TEMP:{temp:.0f}°C", font=self._f_small, fill=tc)

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
    def _dist(p1, p2) -> float:
        return ((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2) ** 0.5
