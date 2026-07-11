"""vp_config.py - Configuracion del reproductor de video"""
import os

# --- RUTAS ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CARTELAS_DIR = os.path.join(BASE_DIR, 'cartelas')

# --- EXTENSIONES DE VIDEO ---
VIDEO_EXT = ('.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.m4v')

# --- CARPETAS DONDE BUSCAR VIDEOS ---
SEARCH_FOLDERS = [
    os.path.join(BASE_DIR, 'movies'),
    os.path.join(BASE_DIR, 'Movies'),
    os.path.join(BASE_DIR, 'videos'),
    BASE_DIR,
    os.path.expanduser('~/Videos'),
    '/media/pi',
    '/mnt',
]

# --- VOLUMEN Y SEEK ---
VOLUME_STEP = 5
SEEK_STEP = 10

# --- PANTALLA ST7789 (2 pulgadas, 240x320, SPI) ---
ST7789_CONFIG = {
    'width': 240,
    'height': 320,
    'rotation': 0,
    'baudrate': 40000000,
    'dc_pin': 27,     # GPIO27
    'rst_pin': 22,     # GPIO22
    'cs_pin': 17,     # GPIO17
    'sclk_pin': 11,   # GPIO11 (SCLK)
    'mosi_pin': 10,   # GPIO10 (MOSI)
    'display_name': '2.0"',
    'bgr': False,
    'invert': True,
}

# --- PANTALLA HDMI ---
HDMI_CONFIG = {
    'fullscreen': True,
    'noframe': True,
}

# --- MANDO XBOX ---
CONTROLLER_DEADZONE = 0.3
