"""
config_loader.py - Cargador centralizado de configuración
Lee config.ini desde la raíz del proyecto. Nunca expone tokens en logs.
"""
import configparser
import os

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.ini")
_cfg = configparser.ConfigParser()

def _load():
    if not os.path.exists(_CONFIG_PATH):
        raise FileNotFoundError(
            f"config.ini no encontrado en {_CONFIG_PATH}\n"
            f"Copia config.ini.example a config.ini y rellena tus credenciales."
        )
    with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
        _cfg.read_file(f)

_load()

# ── ThingsBoard ──
TB_HOST              = _cfg.get("thingsboard", "host",             fallback="mqtt.thingsboard.cloud")
TB_TOKEN             = _cfg.get("thingsboard", "token",            fallback="")
TB_PUBLISH_INTERVAL  = _cfg.getint("thingsboard", "publish_interval", fallback=5)

# ── EMQX ──
EMQX_HOST     = _cfg.get("emqx", "host",      fallback="")
EMQX_PORT     = _cfg.getint("emqx", "port",   fallback=8883)
EMQX_USERNAME = _cfg.get("emqx", "username",  fallback="")
EMQX_PASSWORD = _cfg.get("emqx", "password",  fallback="")
EMQX_CLIENT   = _cfg.get("emqx", "client_id", fallback="raspi_motomami")

# ── GPS ──
GPS_AT_PORT   = _cfg.get("gps", "at_port",  fallback="/dev/ttyUSB2")
GPS_NMEA_PORT = _cfg.get("gps", "nmea_port", fallback="/dev/ttyUSB1")
GPS_BAUD      = _cfg.getint("gps", "baud",  fallback=115200)
MAP_ZOOM      = _cfg.getint("gps", "map_zoom", fallback=16)
MAX_ROUTE_PTS = _cfg.getint("gps", "max_route_points", fallback=50)

# ── Rutas ──
MUSIC_DIR  = _cfg.get("paths", "music_dir",   fallback="/home/motomami/music")
MOVIES_DIR = _cfg.get("paths", "movies_dir",  fallback="/home/motomami/movies")

# ── Display ──
FB1_PATH = _cfg.get("display", "fb1",    fallback="/dev/fb1")
FB2_PATH = _cfg.get("display", "fb2",    fallback="/dev/fb2")
DISP_W   = _cfg.getint("display", "width",  fallback=320)
DISP_H   = _cfg.getint("display", "height", fallback=240)

# ── Sistema ──
TELEMETRY_INTERVAL = _cfg.getint("system", "telemetry_interval",   fallback=5)
GPS_REFRESH        = _cfg.getfloat("system", "gps_refresh_interval", fallback=2.0)
MAP_TILE_CACHE     = _cfg.get("system", "map_tile_cache", fallback="/tmp/maptiles")

def summary():
    """Retorna resumen de config SIN exponer tokens."""
    return {
        "tb_host": TB_HOST,
        "tb_token": TB_TOKEN[:4] + "****" if TB_TOKEN else "NO CONFIGURADO",
        "gps_port": GPS_AT_PORT,
        "music_dir": MUSIC_DIR,
        "movies_dir": MOVIES_DIR,
        "telemetry_interval": TELEMETRY_INTERVAL,
    }
