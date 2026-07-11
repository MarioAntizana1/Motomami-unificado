#!/usr/bin/env python3
"""
Prefiere descargar tiles de OpenStreetMap para un área o ruta.
Útil para tener mapas offline antes de un viaje.

Uso:
    python tools/prefetch_tiles.py --bbox -33.5 -70.8 -33.3 -70.5 --zooms 14 15 16
    python tools/prefetch_tiles.py --route archivo_kml.kml
    python tools/prefetch_tiles.py --list-cache
"""
import argparse
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))
from libs.map_renderer import MapRenderer, cache_stats, TILE_CACHE_DIR

def main():
    p = argparse.ArgumentParser(description="Pre-descarga tiles OSM para uso offline")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--bbox", nargs=4, type=float, metavar=("MIN_LAT", "MIN_LON", "MAX_LAT", "MAX_LON"),
                   help="Bounding box: min_lat min_lon max_lat max_lon")
    g.add_argument("--route", type=str, metavar="FILE",
                   help="Archivo KML/GPX con la ruta (calcula bbox automático)")
    g.add_argument("--list-cache", action="store_true", help="Muestra estadísticas del caché")
    p.add_argument("--zooms", nargs="+", type=int, default=[14, 15, 16],
                   help="Niveles de zoom (default: 14 15 16)")
    args = p.parse_args()

    if args.list_cache:
        stats = cache_stats()
        try:
            import shutil
            size = sum(f.stat().st_size for f in os.scandir(TILE_CACHE_DIR) if f.is_file())
        except:
            size = 0
        print(f"Directorio de caché: {TILE_CACHE_DIR}")
        print(f"Tamaño aproximado:   {size / 1024 / 1024:.1f} MB")
        print(f"Hits:                {stats['hits']}")
        print(f"Misses:              {stats['misses']}")
        print(f"Downloads totales:   {stats['downloads']}")
        return

    if args.bbox:
        min_lat, min_lon, max_lat, max_lon = args.bbox
    elif args.route:
        # Extraer bbox del archivo usando min/max de coordenadas
        coords = _parse_route_file(args.route)
        if not coords:
            print(f"[ERROR] No se pudieron extraer coordenadas de {args.route}")
            sys.exit(1)
        lats = [c[0] for c in coords]
        lons = [c[1] for c in coords]
        min_lat, max_lat = min(lats), max(lats)
        min_lon, max_lon = min(lons), max(lons)
        print(f"Ruta: {len(coords)} puntos")
    else:
        return

    pad = 0.02
    min_lat -= pad
    max_lat += pad
    min_lon -= pad
    max_lon += pad

    print(f"Área: {min_lat:.4f},{min_lon:.4f} a {max_lat:.4f},{max_lon:.4f}")
    print(f"Zooms: {args.zooms}")
    total = MapRenderer.prefetch_area(min_lat, min_lon, max_lat, max_lon, args.zooms)
    print(f"\n[OK] {total} tiles cacheados en {TILE_CACHE_DIR}")

def _parse_route_file(path: str) -> list:
    """Extrae lista de (lat, lon) de KML o GPX"""
    ext = os.path.splitext(path)[1].lower()
    coords = []

    if ext == ".kml":
        import xml.etree.ElementTree as ET
        ns = {"kml": "http://www.opengis.net/kml/2.2"}
        tree = ET.parse(path)
        for placemark in tree.findall(".//kml:Placemark", ns):
            for coord_elem in placemark.findall(".//kml:coordinates", ns):
                for point in coord_elem.text.strip().split():
                    parts = point.split(",")
                    if len(parts) >= 2:
                        coords.append((float(parts[1]), float(parts[0])))
    elif ext == ".gpx":
        import xml.etree.ElementTree as ET
        ns = {"gpx": "http://www.topografix.com/GPX/1/1"}
        tree = ET.parse(path)
        for trkpt in tree.findall(".//gpx:trkpt", ns):
            lat = float(trkpt.attrib["lat"])
            lon = float(trkpt.attrib["lon"])
            coords.append((lat, lon))
    elif ext == ".txt":
        with open(path) as f:
            for line in f:
                parts = line.strip().split(",")
                if len(parts) >= 2:
                    coords.append((float(parts[0]), float(parts[1])))
    else:
        print(f"[WARN] Formato no reconocido: {ext}. Probando como CSV lat,lon")
        with open(path) as f:
            for line in f:
                parts = line.strip().split(",")
                if len(parts) >= 2:
                    coords.append((float(parts[0]), float(parts[1])))

    return coords

if __name__ == "__main__":
    main()
