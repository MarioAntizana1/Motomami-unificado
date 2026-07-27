"""
theme.py - Sistema de tema centralizado (día/noche) para MotoMami.

Uso:
    from libs.theme import get_theme, toggle_mode, get_mode
    t = get_theme("main_menu")
    d.text((0, 0), "Hola", font=f, fill=t.TEXT)

El modo se persiste en config.ini sección [ui] theme = day|night.
"""
import configparser
import os
import threading
from dataclasses import dataclass, replace

_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "config.ini",
)


@dataclass
class Theme:
    # Backgrounds
    BG:         tuple = (0, 0, 0)
    BG_DIM:     tuple = (10, 10, 15)
    BG_MID:     tuple = (20, 22, 30)
    BG_LIGHT:   tuple = (35, 38, 50)

    # Text
    TEXT:       tuple = (220, 220, 230)
    TEXT_DIM:   tuple = (130, 135, 150)
    TEXT_MUTED: tuple = (80, 85, 100)

    # Accent (override por app)
    ACCENT:     tuple = (100, 200, 255)
    ACCENT_DIM: tuple = (20, 60, 90)

    # Semantic
    GOOD:  tuple = (0, 220, 80)
    WARN:  tuple = (255, 180, 0)
    ERROR: tuple = (255, 60, 60)
    INFO:  tuple = (80, 180, 255)

    # Texto sobre fondo de acento sólido (header del detalle en main_menu)
    ON_ACCENT: tuple = (0, 0, 0)


# ── Paletas base por modo ──

NIGHT = Theme()

DAY = Theme(
    BG=(232, 234, 238),
    BG_DIM=(220, 223, 229),
    BG_MID=(200, 205, 215),
    BG_LIGHT=(180, 188, 202),
    TEXT=(25, 28, 35),
    TEXT_DIM=(70, 76, 90),
    TEXT_MUTED=(110, 118, 135),
    ACCENT_DIM=(190, 215, 235),
    GOOD=(0, 150, 50),
    WARN=(200, 120, 0),
    ERROR=(210, 30, 30),
    INFO=(0, 110, 200),
    ON_ACCENT=(0, 0, 0),
)

# ── Acentos por app (mismo color en ambos modos) ──
_APP_ACCENTS = {
    "main_menu":   (100, 255, 100),
    "gps":         (0, 220, 80),
    "music":       (200, 100, 255),
    "video":       (0, 200, 255),
    "camera":      (255, 100, 100),
    "connections": (80, 180, 255),
    "doom":        (255, 80, 80),
    "bluetooth":   (80, 160, 255),
    "mqtt":        (0, 200, 255),
    "telem":       (50, 200, 255),
}

_lock = threading.Lock()
_mode = "night"


def _read_mode_from_config() -> str:
    try:
        cfg = configparser.ConfigParser()
        cfg.read(_CONFIG_PATH, encoding="utf-8")
        m = cfg.get("ui", "theme", fallback="night").strip().lower()
        return "day" if m == "day" else "night"
    except Exception:
        return "night"


def get_mode() -> str:
    with _lock:
        return _mode


def set_mode(mode: str, persist: bool = True):
    global _mode
    mode = "day" if str(mode).strip().lower() == "day" else "night"
    with _lock:
        _mode = mode
    if persist:
        _save_mode(mode)


def toggle_mode() -> str:
    new = "day" if get_mode() == "night" else "night"
    set_mode(new)
    return new


def get_theme(app_name: str = "") -> Theme:
    """Retorna el Theme del modo actual, con acento de la app si existe."""
    base = DAY if get_mode() == "day" else NIGHT
    accent = _APP_ACCENTS.get(app_name)
    if accent is None:
        return base
    return replace(base, ACCENT=accent)


def accent(color: tuple) -> tuple:
    """Oscurece un color brillante en modo día para que sea legible
    sobre fondo claro. En modo noche retorna el color intacto."""
    if get_mode() == "day":
        return tuple(min(255, int(c * 0.55)) for c in color)
    return color


def _save_mode(mode: str):
    """Persiste el modo en config.ini ([ui] theme). Nunca borra otras claves."""
    try:
        cfg = configparser.ConfigParser()
        if os.path.exists(_CONFIG_PATH):
            cfg.read(_CONFIG_PATH, encoding="utf-8")
        if not cfg.has_section("ui"):
            cfg.add_section("ui")
        cfg.set("ui", "theme", mode)
        with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
            cfg.write(f)
    except Exception as e:
        print(f"[Theme] No se pudo guardar theme en config.ini: {e}")


# Inicializar desde config al importar
_mode = _read_mode_from_config()
