#!/usr/bin/env python3
"""
map_renderer.py - Renderiza mapas de OpenStreetMap para pantallas pequeñas

Usa staticmap (recomendado) o descarga tiles directamente.
Genera imágenes PIL compatibles con las pantallas ST7789 (240x320).
"""

import math
import io
import os
import time
from typing import Optional, Tuple, List
from PIL import Image, ImageDraw, ImageFont

# Intentar importar staticmap
try:
    from staticmap import StaticMap, CircleMarker, Line as SLine
    HAS_STATICMAP = True
except ImportError:
    HAS_STATICMAP = False
    print("[MAP] staticmap no disponible. Usando modo tiles directos.")

# Configuración de caché de tiles
try:
    import config_loader as _cfg
    _TILE_CACHE = getattr(_cfg, 'MAP_TILE_CACHE', None) or "/tmp/map_tiles"
except Exception:
    _TILE_CACHE = "/tmp/map_tiles"

os.makedirs(_TILE_CACHE, exist_ok=True)
TILE_CACHE_DIR = _TILE_CACHE

_cache_hits = 0
_cache_misses = 0
_cache_downloads = 0

def cache_stats() -> dict:
    return {"hits": _cache_hits, "misses": _cache_misses, "downloads": _cache_downloads}


class MapRenderer:
    """
    Renderiza mapas en imágenes PIL para pantallas pequeñas.
    
    Dos modos:
      1. staticmap (si está instalado) - más fácil
      2. Tiles directos de OSM (fallback) - más control
    """

    def __init__(self, width: int = 320, height: int = 240, zoom: int = 16):
        self.width = width
        self.height = height
        self.zoom = zoom
        self.user_position = None  # (lat, lon) último punto del usuario

        # Intentar cargar una fuente pequeña
        self.font = None
        for font_path in [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]:
            try:
                self.font = ImageFont.truetype(font_path, 10)
                break
            except:
                pass
        if self.font is None:
            self.font = ImageFont.load_default()

    def render_map_staticmap(self, lat: float, lon: float,
                             route_points: List[Tuple[float, float]] = None) -> Image.Image:
        """
        Renderiza un mapa usando staticmap (sin control de zoom).
        staticmap auto-calcula el zoom desde el extent de los features.
        """
        if not HAS_STATICMAP:
            return self._create_fallback_map(lat, lon, "staticmap no instalado")

        try:
            m = StaticMap(self.width, self.height)

            if route_points and len(route_points) > 1:
                coords = [(lon, lat) for lat, lon in route_points]
                line = SLine(coords, 'blue', 2)
                m.add_line(line)

            marker = CircleMarker((lon, lat), 'red', 8)
            m.add_marker(marker)

            image = m.render()

            draw = ImageDraw.Draw(image)
            info = f"⊙ {lat:.4f}, {lon:.4f}"
            draw.text((4, 4), info, font=self.font, fill=(255, 255, 255))

            return image

        except Exception as e:
            print(f"[MAP] Error en staticmap: {e}")
            return self._create_fallback_map(lat, lon, f"Map Error: {e}")

    def render_map_tiles(self, lat: float, lon: float,
                         route_points: List[Tuple[float, float]] = None) -> Image.Image:
        """
        Renderiza mapa descargando tiles de OpenStreetMap directamente.

        Esto da más control sobre la apariencia.
        """
        try:
            import requests

            # Calcular coordenadas de tile para la posición central
            center_tile_x, center_tile_y = self._latlon_to_tile(lat, lon, self.zoom)
            center_px_x, center_px_y = self._latlon_to_pixel(lat, lon, self.zoom)

            # Calcular cuántos tiles necesitamos (cada tile = 256x256)
            tiles_across = math.ceil(self.width / 256) + 2
            tiles_down = math.ceil(self.height / 256) + 2

            # Tile central (redondeado)
            tile_center_x = int(center_tile_x)
            tile_center_y = int(center_tile_y)

            # Offset del centro del tile en píxeles
            offset_x = int((center_tile_x - tile_center_x) * 256)
            offset_y = int((center_tile_y - tile_center_y) * 256)

            # Crear canvas
            map_image = Image.new('RGB', (self.width, self.height), (200, 200, 200))

            # Calcular tiles a descargar
            start_tile_x = tile_center_x - tiles_across // 2
            start_tile_y = tile_center_y - tiles_down // 2

            for ty in range(tiles_down):
                for tx in range(tiles_across):
                    tile_x = start_tile_x + tx
                    tile_y = start_tile_y + ty

                    tile_img = self._get_tile(tile_x, tile_y, self.zoom)

                    if tile_img:
                        # Posición en píxeles del tile en el canvas
                        pos_x = (tx - tiles_across // 2) * 256 - offset_x + self.width // 2
                        pos_y = (ty - tiles_down // 2) * 256 - offset_y + self.height // 2

                        # Solo pegar si está dentro del canvas
                        if (pos_x + 256 > 0 and pos_x < self.width and
                                pos_y + 256 > 0 and pos_y < self.height):
                            map_image.paste(tile_img, (pos_x, pos_y))

            # Dibujar ruta
            draw = ImageDraw.Draw(map_image)
            if route_points and len(route_points) > 1:
                for i in range(len(route_points) - 1):
                    p1 = self._latlon_to_pixel_on_map(
                        route_points[i][0], route_points[i][1],
                        lat, lon, tile_center_x, tile_center_y,
                        offset_x, offset_y
                    )
                    p2 = self._latlon_to_pixel_on_map(
                        route_points[i + 1][0], route_points[i + 1][1],
                        lat, lon, tile_center_x, tile_center_y,
                        offset_x, offset_y
                    )
                    if p1 and p2:
                        draw.line([p1, p2], fill=(0, 0, 255), width=2)

            # Dibujar marcador de posición
            marker_x = self.width // 2
            marker_y = self.height // 2
            self._draw_marker(draw, marker_x, marker_y, (255, 0, 0))

            # Info en esquina
            info = f"⊙ {lat:.4f}, {lon:.4f}"
            draw.text((4, 4), info, font=self.font, fill=(0, 0, 0))

            return map_image

        except Exception as e:
            print(f"[MAP] Error en tiles: {e}")
            return self._create_fallback_map(lat, lon, f"Error: {e}")

    def render_map(self, lat: float, lon: float,
                   route_points: List[Tuple[float, float]] = None) -> Image.Image:
        """Renderiza mapa: tiles (soporta zoom) → staticmap → fallback"""
        self.user_position = (lat, lon)

        # Tiles directos (ruta principal, soporta zoom controlable)
        try:
            return self.render_map_tiles(lat, lon, route_points)
        except Exception as e:
            print(f"[MAP] Error en tiles: {e}")
            if HAS_STATICMAP:
                return self.render_map_staticmap(lat, lon, route_points)
            return self._create_fallback_map(lat, lon, f"Tile Error: {e}")

    def _create_fallback_map(self, lat: float, lon: float,
                             error_msg: str = "") -> Image.Image:
        """Crea un mapa de respaldo simple cuando hay error"""
        img = Image.new('RGB', (self.width, self.height), (30, 30, 30))
        draw = ImageDraw.Draw(img)

        # Círculo concéntrico simulando mapa
        cx, cy = self.width // 2, self.height // 2
        for r in range(40, min(self.width, self.height) // 2, 40):
            draw.ellipse([cx - r, cy - r, cx + r, cy + r],
                         outline=(60, 60, 60), width=1)

        # Líneas de retícula
        for x in range(0, self.width, 40):
            draw.line([(x, 0), (x, self.height)], fill=(40, 40, 40), width=1)
        for y in range(0, self.height, 40):
            draw.line([(0, y), (self.width, y)], fill=(40, 40, 40), width=1)

        # Marcador
        self._draw_marker(draw, cx, cy, (255, 0, 0))

        # Texto
        y_pos = 10
        draw.text((10, y_pos), f"GPS: {lat:.4f}, {lon:.4f}",
                  font=self.font, fill=(255, 255, 255))
        y_pos += 15
        draw.text((10, y_pos), f"Zoom: {self.zoom}",
                  font=self.font, fill=(200, 200, 200))
        if error_msg:
            y_pos += 15
            draw.text((10, y_pos), error_msg[:30],
                      font=self.font, fill=(255, 100, 100))

        return img

    @staticmethod
    def _draw_marker(draw, x: int, y: int, color: Tuple[int, int, int]):
        """Dibuja un marcador de posición tipo pin"""
        # Círculo exterior
        r = 6
        draw.ellipse([x - r, y - r, x + r, y + r], fill=color)
        # Círculo interior blanco
        draw.ellipse([x - 2, y - 2, x + 2, y + 2], fill=(255, 255, 255))
        # Sombra
        draw.ellipse([x - r, y - r, x + r, y + r], outline=(200, 0, 0), width=1)

    @staticmethod
    def _latlon_to_tile(lat: float, lon: float, zoom: int) -> Tuple[float, float]:
        """Convierte lat/lon a coordenadas de tile (continuas)"""
        import math
        lat_rad = math.radians(lat)
        n = 2.0 ** zoom
        x = (lon + 180.0) / 360.0 * n
        y = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
        return (x, y)

    @staticmethod
    def _latlon_to_pixel(lat: float, lon: float, zoom: int) -> Tuple[int, int]:
        """Convierte lat/lon a píxeles en el mundo de tiles (256*2^zoom)"""
        tile_x, tile_y = MapRenderer._latlon_to_tile(lat, lon, zoom)
        px_x = int(tile_x * 256)
        px_y = int(tile_y * 256)
        return (px_x, px_y)

    def _latlon_to_pixel_on_map(self, lat: float, lon: float,
                                 center_lat: float, center_lon: float,
                                 tile_center_x: int, tile_center_y: int,
                                 offset_x: int, offset_y: int) -> Optional[Tuple[int, int]]:
        """Convierte lat/lon a píxeles en la imagen del mapa renderizado"""
        px, py = self._latlon_to_pixel(lat, lon, self.zoom)
        center_px_x = tile_center_x * 256 + offset_x
        center_px_y = tile_center_y * 256 + offset_y

        map_x = px - center_px_x + self.width // 2
        map_y = py - center_px_y + self.height // 2

        return (map_x, map_y)

    def _get_tile(self, tile_x: int, tile_y: int, zoom: int) -> Optional[Image.Image]:
        """Descarga un tile de OSM con caché persistente"""
        global _cache_hits, _cache_misses, _cache_downloads
        cache_dir = os.path.join(TILE_CACHE_DIR, str(zoom))
        cache_path = os.path.join(cache_dir, f"{tile_x}_{tile_y}.png")

        if os.path.exists(cache_path):
            try:
                _cache_hits += 1
                return Image.open(cache_path)
            except:
                pass

        _cache_misses += 1
        try:
            import requests
            url = f"https://tile.openstreetmap.org/{zoom}/{tile_x}/{tile_y}.png"
            headers = {
                'User-Agent': 'RPi-GPS-MapViewer/1.0 (Raspberry Pi Zero 2W)'
            }
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                _cache_downloads += 1
                img = Image.open(io.BytesIO(resp.content))
                os.makedirs(cache_dir, exist_ok=True)
                img.save(cache_path)
                return img
        except Exception as e:
            print(f"[MAP] Error descargando tile {zoom}/{tile_x}/{tile_y}: {e}")

        return None

    @staticmethod
    def prefetch_area(min_lat: float, min_lon: float,
                      max_lat: float, max_lon: float,
                      zooms: List[int] = None, verbose: bool = True):
        """
        Pre-descarga tiles para un área geográfica.
        Útil para tener mapas offline antes de un viaje.

        Args:
            min_lat, min_lon: esquina suroeste
            max_lat, max_lon: esquina noreste
            zooms: lista de niveles de zoom (default: [14,15,16])
        """
        if zooms is None:
            zooms = [14, 15, 16]
        total = 0
        for z in zooms:
            tx1, ty1 = MapRenderer._latlon_to_tile(max_lat, min_lon, z)
            tx2, ty2 = MapRenderer._latlon_to_tile(min_lat, max_lon, z)
            x1, x2 = int(min(tx1, tx2)), int(max(tx1, tx2)) + 1
            y1, y2 = int(min(ty1, ty2)), int(max(ty1, ty2)) + 1
            r = MapRenderer(zoom=z)
            for x in range(x1, x2):
                for y in range(y1, y2):
                    if r._get_tile(x, y, z):
                        total += 1
                        if verbose and total % 50 == 0:
                            print(f"[MAP] Prefetch z{z}: {total} tiles...")
            if verbose:
                print(f"[MAP] Zoom {z}: {x2-x1}x{y2-y1} = {(x2-x1)*(y2-y1)} tiles")
        if verbose:
            print(f"[MAP] Prefetch completo: {total} tiles descargados")
        return total


# === TEST RÁPIDO ===
if __name__ == "__main__":
    # Coordenadas de ejemplo (Lima, Perú)
    test_lat = -12.0496
    test_lon = -77.0118

    renderer = MapRenderer(240, 320, zoom=16)
    img = renderer.render_map(test_lat, test_lon)

    # Guardar para verificar
    img.save("/tmp/test_map.png")
    print(f"[MAP] Mapa guardado en /tmp/test_map.png ({img.size})")
