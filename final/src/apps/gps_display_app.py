#!/usr/bin/env python3
"""
gps_display_app.py - Aplicación principal GPS + Mapas + 2 Pantallas

Muestra:
  Pantalla #1 (CS=GPIO17): Mapa con posición actual
  Pantalla #2 (CS=GPIO23): Datos de navegación (satélites, altitud, velocidad, etc.)

Hardware:
  - SIM7600-G en /dev/ttyUSB2 (115200 baud)
  - 2x Pantallas GMT020-02 (ST7789, 240x320) en SPI compartido
  - RPi Zero 2W

Uso:
  cd src && sudo python3 apps/gps_display_app.py

Dependencias:
  pip install pyserial Pillow staticmap requests
"""

import time
import sys
import os

# ── Asegurar rutas de módulos locales ──
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_BASE_DIR = os.path.dirname(_THIS_DIR)  # src/
for _p in [os.path.join(_BASE_DIR, 'drivers'),
            os.path.join(_BASE_DIR, 'lib')]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import threading
import math
import json
import subprocess
import re
import board
import digitalio
from PIL import Image, ImageDraw, ImageFont

# Nuestros módulos
from fb_display import FbDisplay, daemon_available
from map_renderer import MapRenderer
from sim7600_gps import SIM7600GPS, SIM7600GPSData

# Control Xbox opcional
try:
    from vp_controller import XboxController
    HAS_XBOX = True
except ImportError:
    HAS_XBOX = False

# MQTT + Sistema (import opcional - si no está instalado se omite la publicación)
try:
    import paho.mqtt.client as mqtt
    HAS_MQTT = True
except ImportError:
    HAS_MQTT = False
    print("[MQTT] paho-mqtt no instalado. La telemetria a ThingsBoard estara desactivada.")
    print("       Instala con: sudo pip3 install paho-mqtt")
import psutil

# ═══════════════════════════════════════════════════════
#  CONFIGURACIÓN
# ═══════════════════════════════════════════════════════

# Puertos
GPS_AT_PORT = "/dev/ttyUSB2"   # Puerto de comandos AT
GPS_NMEA_PORT = "/dev/ttyUSB1"  # Puerto NMEA (datos GPS crudos)
GPS_BAUD = 115200

# ── ThingsBoard ──
THINGSBOARD_HOST = 'mqtt.thingsboard.cloud'
ACCESS_TOKEN = 'YOUR_THINGSBOARD_ACCESS_TOKEN'
MQTT_PUBLISH_INTERVAL = 10  # segundos entre publicaciones MQTT

# Zoom inicial del mapa (15=calle, 16=detalle, 17=más detalle)
MAP_ZOOM = 16

# Intervalo de refresco (segundos)
REFRESH_INTERVAL = 2.0

# Historial de ruta (puntos para dibujar)
MAX_ROUTE_POINTS = 50  # Guardar últimos N puntos

# ── Detección USB del SIM7600-G ──
SIM7600_VENDOR = "1e0e"
SIM7600_PRODUCT = "9001"
USB_CHECK_INTERVAL = 5  # segundos entre chequeos USB

# ═══════════════════════════════════════════════════════
#  PINES DE LAS PANTALLAS
# ═══════════════════════════════════════════════════════

# Pantalla #1 - MAPA
CS1_PIN = board.D17   # GPIO17
DC1_PIN = board.D27   # GPIO27
RST1_PIN = board.D22  # GPIO22

# Pantalla #2 - DATOS
CS2_PIN = board.D24   # GPIO24
DC2_PIN = board.D25   # GPIO25
RST2_PIN = board.D23  # GPIO23


class GPSDisplayApp:
    """Aplicación principal que coordina GPS + Mapas + 2 Pantallas"""

    def __init__(self):
        print("╔══════════════════════════════════════════╗")
        print("║     GPS + MAPAS + 2 PANTALLAS           ║")
        print("╚══════════════════════════════════════════╝")
        print()

        # Inicializar pantallas
        self._init_displays()

        # Inicializar renderizador de mapas (horizontal)
        self.map_renderer = MapRenderer(
            width=320, height=240, zoom=MAP_ZOOM
        )

        # Inicializar GPS del SIM7600 (vía AT commands)
        self.gps = SIM7600GPS(
            at_port=GPS_AT_PORT,
            baudrate=GPS_BAUD,
            auto_start=False  # Nosotros lo iniciamos cuando detectemos USB
        )
        self.gps.set_callback(self._on_gps_update)

        # Datos de ruta
        self.route_points = []
        self.last_data = SIM7600GPSData()
        self.last_update_time = 0
        self.display_lock = threading.Lock()
        self.running = False

        # Estadísticas
        self.frame_count = 0
        self.start_time = time.time()

        # ── Detección USB SIM7600 ──
        self.sim7600_connected = False
        self.last_usb_check = 0
        self.sim7600_was_connected = False
        self._showed_disconnected = False

        # ── ThingsBoard MQTT ──
        self._init_mqtt()
        self.last_mqtt_publish = 0

        # ── Botón Físico de Salida (GPIO 16) ──
        # Si falla (GPIO busy por menú principal), se ignora y se sale con Ctrl+C
        try:
            self.btn_back = digitalio.DigitalInOut(board.D16)
            self.btn_back.direction = digitalio.Direction.INPUT
            self.btn_back.pull = digitalio.Pull.DOWN
        except Exception:
            self.btn_back = None

        # Xbox Controller
        self.xbox = XboxController() if HAS_XBOX else None
        if self.xbox and self.xbox.connect():
            self.xbox.start()
            print("[GPS App] Mando Xbox conectado!")
        else:
            self.xbox = None

    def _init_displays(self):
        """Inicializa displays via daemon de framebuffer."""
        self.display_map = True   # Flag: display #1 disponible
        self.display_data = True  # Flag: display #2 disponible
        self.fb = FbDisplay(3)    # Canvas 640x240 unificado

        if not daemon_available():
            print("[INIT] ADVERTENCIA: fb_daemon no detectado!")
            self.display_map = None
            self.display_data = None
            return
        print("[INIT] Displays via daemon FB (640x240 canvas)")

        # Mostrar splash
        self._show_splash()

    def _show_splash(self):
        """Muestra pantalla de inicio en el canvas unificado."""
        if not hasattr(self, 'fb') or not self.fb:
            return
        self.fb.blank()
        draw = self.fb.draw()
        W = 320
        H = 240

        try:
            font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 22
            )
            font_small = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14
            )
        except:
            font = ImageFont.load_default()
            font_small = font

        for ox, text, color in [
            (0, "GPS MAPA", (0, 200, 255)),
            (320, "GPS DATOS", (0, 255, 128)),
        ]:
            # Titulo centrado en su mitad
            bbox = draw.textbbox((0, 0), text, font=font)
            tw = bbox[2] - bbox[0]
            x = ox + (W - tw) // 2
            y = H // 2 - 20
            draw.text((x, y), text, font=font, fill=color)

            # Subtitulo
            sub = "Iniciando..."
            bbox2 = draw.textbbox((0, 0), sub, font=font_small)
            sw = bbox2[2] - bbox2[0]
            sx = ox + (W - sw) // 2
            draw.text((sx, y + 30), sub, font=font_small, fill=(200, 200, 200))

        self.fb.update()

    def _push_displays(self, img_left, img_right):
        """Envia dos imagenes PIL (320x240 cada una) al daemon.
        img_left → Display #1, img_right → Display #2."""
        if not hasattr(self, 'fb') or not self.fb:
            return
        full = self.fb.image()
        if img_left:
            full.paste(img_left.resize((320, 240)) if img_left.size != (320, 240) else img_left, (0, 0))
        if img_right:
            full.paste(img_right.resize((320, 240)) if img_right.size != (320, 240) else img_right, (320, 0))
        self.fb.update()

    def _push_display(self, img, side='left'):
        """Envia una imagen a un solo lado del canvas."""
        if not hasattr(self, 'fb') or not self.fb:
            return
        full = self.fb.image()
        ox = 0 if side == 'left' else 320
        if img.size != (320, 240):
            img = img.resize((320, 240))
        full.paste(img, (ox, 0))
        self.fb.update()

    # ────────────────────────────────────────────────
    #  DETECCIÓN USB - SIM7600-G
    # ────────────────────────────────────────────────

    @staticmethod
    def _check_sim7600_usb() -> bool:
        """Verifica si el SIM7600-G está conectado por USB.
        Busca idVendor=1e0e en lsusb, o verifica si existe /dev/ttyUSB2."""
        # Fallback rápido: Si existe el puerto AT /dev/ttyUSB2, asumimos conectado
        if os.path.exists("/dev/ttyUSB2"):
            return True

        try:
            # Método 1: lsusb
            result = subprocess.run(
                ["lsusb"],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if SIM7600_VENDOR in line.lower():
                        return True

            # Método 2: /sys/bus/usb/devices (fallback)
            for root, dirs, files in os.walk("/sys/bus/usb/devices"):
                for d in dirs:
                    id_vendor_path = os.path.join(root, d, "idVendor")
                    if os.path.exists(id_vendor_path):
                        with open(id_vendor_path) as f:
                            vendor = f.read().strip()
                        if vendor == SIM7600_VENDOR:
                            return True
                break  # Solo primer nivel

        except Exception as e:
            print(f"[USB] Error verificando SIM7600: {e}")

        return False

    @staticmethod
    def _check_tty_usb() -> list:
        """Lista los /dev/ttyUSB* disponibles"""
        ttys = []
        try:
            for f in os.listdir("/dev"):
                if f.startswith("ttyUSB"):
                    ttys.append(f"/dev/{f}")
        except FileNotFoundError:
            pass
        return sorted(ttys)

    def _render_usb_disconnected_screen(self, side='left'):
        """Muestra pantalla de 'SIM7600 desconectado' en el lado indicado.
        side: 'left' (Display #1) o 'right' (Display #2)."""
        if not hasattr(self, 'fb') or not self.fb:
            return
        W, H = 320, 240
        img = Image.new("RGB", (W, H), (15, 0, 0))
        draw = ImageDraw.Draw(img)

        try:
            font_big = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 22
            )
            font_normal = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14
            )
        except:
            font_big = ImageFont.load_default()
            font_normal = font_big

        # Icono de "no USB"
        cx, cy = W // 2, H // 2 - 40
        draw.ellipse([cx - 20, cy - 20, cx + 20, cy + 20], outline=(255, 50, 50), width=3)
        draw.line([(cx - 12, cy - 12), (cx + 12, cy + 12)], fill=(255, 50, 50), width=3)
        draw.line([(cx + 12, cy - 12), (cx - 12, cy + 12)], fill=(255, 50, 50), width=3)

        # SIM7600-G DESCONECTADO (en una línea para horizontal)
        text = "SIM7600-G DESCONECTADO"
        bbox = draw.textbbox((0, 0), text, font=font_big)
        tw = bbox[2] - bbox[0]
        draw.text(((W - tw) // 2, H // 2 + 5), text, font=font_big, fill=(255, 80, 80))

        # Puertos disponibles
        ttys = self._check_tty_usb()
        if ttys:
            tty_text = f"Puertos: {', '.join(ttys)}"
            bbox3 = draw.textbbox((0, 0), tty_text, font=font_normal)
            tw3 = bbox3[2] - bbox3[0]
            draw.text(((W - tw3) // 2, H // 2 + 40), tty_text, font=font_normal, fill=(200, 200, 200))
        else:
            no_tty = "No hay puertos ttyUSB"
            bbox3 = draw.textbbox((0, 0), no_tty, font=font_normal)
            tw3 = bbox3[2] - bbox3[0]
            draw.text(((W - tw3) // 2, H // 2 + 40), no_tty, font=font_normal, fill=(100, 100, 100))

        instr = "Conecta el modulo USB"
        bbox4 = draw.textbbox((0, 0), instr, font=font_normal)
        tw4 = bbox4[2] - bbox4[0]
        draw.text(((W - tw4) // 2, H // 2 + 65), instr, font=font_normal, fill=(150, 150, 150))

        self._push_display(img, side)

    # ────────────────────────────────────────────────
    #  MQTT - ThingsBoard
    # ────────────────────────────────────────────────

    def _init_mqtt(self):
        """Inicializa conexión MQTT con ThingsBoard"""
        if not HAS_MQTT:
            print("[MQTT] Desactivado (paho-mqtt no instalado)")
            self.mqtt_client = None
            return
        print("[MQTT] Conectando a ThingsBoard...")
        try:
            self.mqtt_client = mqtt.Client()
            self.mqtt_client.username_pw_set(ACCESS_TOKEN)
            self.mqtt_client.connect(THINGSBOARD_HOST, 1883, 60)
            self.mqtt_client.loop_start()
            print(f"[MQTT] Conectado a {THINGSBOARD_HOST} como {ACCESS_TOKEN[:8]}...")
        except Exception as e:
            print(f"[MQTT] Error conectando: {e}")
            self.mqtt_client = None

    def _publish_to_thingsboard(self, gps_data: SIM7600GPSData):
        """Publica datos de GPS + sistema a ThingsBoard"""
        if not self.mqtt_client:
            return

        lat, lon = gps_data.get_coordinates_decimal()

        payload = {
            # GPS
            "latitude": lat,
            "longitude": lon,
            "altitude": gps_data.altitude,
            "speed": gps_data.speed_kmh,
            "track_angle": gps_data.track_angle,
            "num_satellites": gps_data.num_satellites,
            "gps_on": 1 if gps_data.gps_on else 0,
            "has_fix": 1 if gps_data.has_fix else 0,
            "gps_time_utc": gps_data.time,
            "gps_date": gps_data.date,
            # Sistema RPi
            **self._get_system_telemetry(),
        }

        try:
            result = self.mqtt_client.publish(
                "v1/devices/me/telemetry",
                json.dumps(payload)
            )
            if result.rc == 0:
                print(f"[MQTT] Publicado OK - Lat:{lat:.4f} Lon:{lon:.4f} "
                      f"Sats:{gps_data.num_satellites} Alt:{gps_data.altitude:.1f}m "
                      f"Vel:{gps_data.speed_kmh:.1f}km/h")
            else:
                print(f"[MQTT] Error publicación: rc={result.rc}")
        except Exception as e:
            print(f"[MQTT] Error: {e}")

    @staticmethod
    def _get_system_telemetry() -> dict:
        """Recolecta telemetría del sistema RPi"""
        data = {}

        # CPU
        cpu_percent = psutil.cpu_percent(percpu=False)
        data["cpu"] = cpu_percent
        cpu_freq = psutil.cpu_freq()
        if cpu_freq:
            data["cpu_freq"] = round(cpu_freq.current, 1)

        # Temperatura CPU
        if hasattr(psutil, "sensors_temperatures"):
            temps = psutil.sensors_temperatures()
            if "cpu_thermal" in temps:
                data["cpu_temp"] = round(temps["cpu_thermal"][0].current, 1)
            elif "coretemp" in temps:
                data["cpu_temp"] = round(temps["coretemp"][0].current, 1)

        # Memoria RAM
        mem = psutil.virtual_memory()
        data["ram"] = round(mem.percent, 1)
        data["ram_used_mb"] = round(mem.used / 1024 / 1024, 0)
        data["ram_total_mb"] = round(mem.total / 1024 / 1024, 0)

        # Disco
        disk = psutil.disk_usage('/')
        data["disk"] = round(disk.percent, 1)
        data["disk_used_gb"] = round(disk.used / 1024 / 1024 / 1024, 1)
        data["disk_total_gb"] = round(disk.total / 1024 / 1024 / 1024, 1)

        # Tiempo actividad
        data["uptime"] = round(time.time() - psutil.boot_time(), 0)

        return data

    # ────────────────────────────────────────────────

    def _on_gps_update(self, data: SIM7600GPSData):
        """Callback cuando llegan datos nuevos del GPS del SIM7600"""
        self.last_data = data

    def _render_map_screen(self, data: SIM7600GPSData) -> Image.Image:
        """Renderiza Pantalla #1: Mapa con posición (320x240 horizontal)"""
        if self.display_map is None:
            return Image.new("RGB", (1, 1), (0, 0, 0))
        W, H = 320, 240  # Landscape per-display

        # Actualizar dimensiones del renderizador de mapa
        self.map_renderer.width = W
        self.map_renderer.height = H

        lat, lon = data.get_coordinates_decimal()

        if data.has_fix and lat != 0 and lon != 0:
            # Renderizar mapa
            img = self.map_renderer.render_map(lat, lon, self.route_points)
            draw = ImageDraw.Draw(img)

            try:
                font_small = ImageFont.truetype(
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11
                )
            except:
                font_small = ImageFont.load_default()

            # Barra de estado inferior
            draw.rectangle([0, H - 14, W - 1, H - 1], fill=(0, 0, 0))
            status = (f"GPS:{'SI' if data.has_fix else 'NO'}"
                      f" | Sats:{data.num_satellites}"
                      f" | Vel:{data.speed_kmh:.1f}km/h"
                      f" | Z:{MAP_ZOOM}")
            draw.text((4, H - 12), status, font=font_small, fill=(0, 255, 128))

        else:
            # Sin fix - pantalla de búsqueda (horizontal)
            img = Image.new("RGB", (W, H), (10, 10, 20))
            draw = ImageDraw.Draw(img)

            try:
                font = ImageFont.truetype(
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18
                )
                font_small = ImageFont.truetype(
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12
                )
            except:
                font = ImageFont.load_default()
                font_small = font

            # Animación de búsqueda (centrada en horizontal)
            cx, cy = W // 2, H // 2 - 20
            for i in range(4):
                angle = (time.time() * 2 + i * 1.57) % 6.28
                x = cx + int(30 * math.cos(angle))
                y = cy + int(30 * math.sin(angle))
                draw.ellipse([x - 4, y - 4, x + 4, y + 4], fill=(0, 100, 255))

            # Texto
            text = "BUSCANDO GPS..."
            bbox = draw.textbbox((0, 0), text, font=font)
            tw = bbox[2] - bbox[0]
            draw.text(((W - tw) // 2, cy + 45), text, font=font, fill=(255, 200, 0))

            # Satélites visibles
            if data.num_satellites > 0:
                sub = f"Satelites visibles: {data.num_satellites}"
                bbox2 = draw.textbbox((0, 0), sub, font=font_small)
                sw = bbox2[2] - bbox2[0]
                draw.text(((W - sw) // 2, cy + 70), sub, font=font_small, fill=(200, 200, 200))

        return img

    def _render_data_screen(self, data: SIM7600GPSData) -> Image.Image:
        """Renderiza Pantalla #2: Datos esenciales (320x240 horizontal)"""
        if self.display_data is None:
            return Image.new("RGB", (1, 1), (0, 0, 0))
        W, H = 320, 240  # Landscape per-display
        img = Image.new("RGB", (W, H), (0, 0, 0))
        draw = ImageDraw.Draw(img)

        try:
            font_huge = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 56
            )
            font_big = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 32
            )
            font_normal = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14
            )
            font_small = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11
            )
        except:
            font_huge = ImageFont.load_default()
            font_big = font_huge
            font_normal = font_huge
            font_small = font_huge

        has_fix = data.has_fix

        # ── Barra superior: Estado + Hora ──
        status_text = "FIX OK" if has_fix else "SIN FIX"
        status_color = (0, 220, 0) if has_fix else (255, 100, 0)
        draw.rectangle([0, 0, W - 1, 20], fill=(20, 20, 30))
        circle_color = (0, 255, 0) if has_fix else (255, 100, 0)
        draw.ellipse([6, 6, 14, 14], fill=circle_color)
        draw.text((20, 3), status_text, font=font_normal, fill=status_color)

        # GPS conectado/desconectado + hora
        if data.time and len(data.time) >= 6:
            h, m, s = data.time[:2], data.time[2:4], data.time[4:6]
            gps_status = f"{h}:{m}:{s}"
        else:
            gps_status = "GPS:NO"
        draw.text((W - 100, 3), gps_status, font=font_small, fill=(150, 200, 255))

        # ── LADO IZQUIERDO: Velocidad + Altitud ──
        left_x = 10

        # Velocidad (ENORME)
        y = 30
        draw.text((left_x, y), "VELOCIDAD", font=font_small, fill=(100, 100, 100))
        vel_text = f"{data.speed_kmh:.1f}"
        bbox = draw.textbbox((0, 0), vel_text, font=font_huge)
        tw = bbox[2] - bbox[0]
        vel_color = (255, 255, 255) if has_fix and data.speed_kmh > 0 else (100, 100, 100)
        draw.text((left_x, y + 8), vel_text, font=font_huge, fill=vel_color)
        draw.text((left_x + tw + 5, y + 45), "km/h", font=font_normal, fill=(150, 150, 150))

        # Altitud
        y = 118
        draw.text((left_x, y), "ALTITUD", font=font_small, fill=(100, 100, 100))
        alt_text = f"{data.altitude:.0f} m"
        alt_color = (0, 220, 100) if has_fix else (80, 80, 80)
        bbox = draw.textbbox((0, 0), alt_text, font=font_big)
        tw = bbox[2] - bbox[0]
        draw.text((left_x, y + 8), alt_text, font=font_big, fill=alt_color)

        # ── LÍNEA VERTICAL DIVISORIA ──
        div_x = 175
        draw.line([(div_x, 25), (div_x, H - 55)], fill=(40, 40, 40), width=1)

        # ── LADO DERECHO: Rumbo + Satélites + Info ──
        rx = div_x + 12

        # Rumbo
        y = 30
        draw.text((rx, y), "RUMBO", font=font_small, fill=(100, 100, 100))
        rumbo_color = (255, 200, 50) if has_fix else (80, 80, 80)
        track = data.track_angle

        # Flecha grande
        arrow_cx, arrow_cy = rx + 30, y + 35
        ang_rad = math.radians(track - 90)
        arrow_len = 20
        ax = arrow_cx + int(arrow_len * math.cos(ang_rad))
        ay = arrow_cy + int(arrow_len * math.sin(ang_rad))
        draw.line([(arrow_cx, arrow_cy), (ax, ay)], fill=rumbo_color, width=4)
        tip1_x = ax + int(7 * math.cos(ang_rad + 2.5))
        tip1_y = ay + int(7 * math.sin(ang_rad + 2.5))
        tip2_x = ax + int(7 * math.cos(ang_rad - 2.5))
        tip2_y = ay + int(7 * math.sin(ang_rad - 2.5))
        draw.polygon([(ax, ay), (tip1_x, tip1_y), (tip2_x, tip2_y)], fill=rumbo_color)

        # Valor rumbo
        draw.text((rx + 60, y + 20), f"{track:.0f}°", font=font_big, fill=rumbo_color)

        # Satélites
        y = 95
        draw.text((rx, y), "SATELITES", font=font_small, fill=(100, 100, 100))
        sats_color = (0, 255, 0) if data.num_satellites >= 4 else (255, 200, 0)
        sat_text = f"{data.num_satellites}"
        draw.text((rx, y + 14), sat_text, font=font_big, fill=sats_color)

        # ── BARRA INFERIOR: Estado RPi ──
        y_bar = H - 50
        draw.rectangle([0, y_bar, W - 1, H - 1], fill=(15, 15, 20))
        telemetry = self._get_system_telemetry()
        cpu = telemetry.get('cpu', 0)
        ram = telemetry.get('ram', 0)
        temp = telemetry.get('cpu_temp', 0)

        # CPU
        cpu_color = (0, 255, 0) if cpu < 50 else (255, 200, 0) if cpu < 80 else (255, 0, 0)
        draw.text((10, y_bar + 4), f"CPU", font=font_small, fill=cpu_color)
        draw.rectangle([50, y_bar + 5, 110, y_bar + 13], fill=(30, 30, 30))
        draw.rectangle([50, y_bar + 5, 50 + int(60 * cpu / 100), y_bar + 13], fill=cpu_color)
        draw.text((115, y_bar + 4), f"{cpu:.0f}%", font=font_small, fill=cpu_color)

        # RAM
        draw.text((150, y_bar + 4), f"RAM", font=font_small, fill=(0, 200, 255))
        draw.rectangle([185, y_bar + 5, 245, y_bar + 13], fill=(30, 30, 30))
        draw.rectangle([185, y_bar + 5, 185 + int(60 * ram / 100), y_bar + 13], fill=(0, 200, 255))
        draw.text((250, y_bar + 4), f"{ram:.0f}%", font=font_small, fill=(0, 200, 255))

        # Temp
        if temp > 0:
            temp_color = (0, 255, 0) if temp < 55 else (255, 200, 0) if temp < 70 else (255, 0, 0)
            draw.text((10, y_bar + 18), f"TEMP: {temp:.0f}°C", font=font_small, fill=temp_color)

        return img

    def start(self):
        """Inicia la aplicación"""
        self.running = True
        self.start_time = time.time()

        print("[APP] Iniciando...")
        print("[APP] Pantalla #1 (GPIO17): Mapa")
        print("[APP] Pantalla #2 (GPIO23): Datos navegacion")
        print()

        try:
            while self.running:
                loop_start = time.time()
                now = time.time()

                # ── Verificar Botones de Salir ──
                if self.btn_back and self.btn_back.value:
                    print("\n[APP] Botón Atrás presionado. Saliendo...")
                    self.running = False
                    continue
                if self.xbox:
                    evt = self.xbox.get_event(0.005)
                    while evt:
                        if evt[0] == 'btn' and evt[1] == self.xbox.B:
                            print("\n[APP] Botón B presionado. Saliendo...")
                            self.running = False
                            break
                        evt = self.xbox.get_event(0.005)
                    if not self.running:
                        continue

                # ── Verificar conexión USB del SIM7600 ──
                if now - self.last_usb_check >= USB_CHECK_INTERVAL:
                    self.sim7600_connected = self._check_sim7600_usb()
                    self.last_usb_check = now

                    # Detectar cambio de estado
                    if self.sim7600_connected and not self.sim7600_was_connected:
                        print("[USB] SIM7600-G CONECTADO! Iniciando GPS...")
                        print("[USB] Activando GPS con AT+CGPS=1...")
                        self.gps.start()
                        self.sim7600_was_connected = True
                        self._showed_disconnected = False
                    elif not self.sim7600_connected and self.sim7600_was_connected:
                        print("[USB] SIM7600-G DESCONECTADO! Deteniendo GPS...")
                        self.gps.stop()
                        self.sim7600_was_connected = False
                        self.route_points = []
                        self._showed_disconnected = False

                # ── Si no hay SIM7600, mostrar pantalla de desconexión ──
                if not self.sim7600_connected:
                    if not self._showed_disconnected:
                        with self.display_lock:
                            self._render_usb_disconnected_screen('left')
                            self._render_usb_disconnected_screen('right')
                        self._showed_disconnected = True

                    elapsed = time.time() - loop_start
                    sleep_time = USB_CHECK_INTERVAL - elapsed
                    if sleep_time > 0:
                        time.sleep(sleep_time)
                    continue

                # ── SIM7600 conectado: obtener datos GPS ──
                data = self.gps.get_data()
                lat, lon = data.get_coordinates_decimal()

                # Actualizar ruta si hay fix y posición válida
                if data.has_fix and lat != 0 and lon != 0:
                    if not self.route_points or self._distance(
                        self.route_points[-1][0], self.route_points[-1][1],
                        lat, lon
                    ) > 0.0001:  # ~10m
                        self.route_points.append((lat, lon))
                        if len(self.route_points) > MAX_ROUTE_POINTS:
                            self.route_points = self.route_points[-MAX_ROUTE_POINTS:]

                # Renderizar pantallas
                with self.display_lock:
                    img_map = self._render_map_screen(data)
                    img_data = self._render_data_screen(data)

                    if self.display_map:
                        self._push_displays(img_map, img_data)

                self.frame_count += 1

                # ── Publicar a ThingsBoard ──
                if now - self.last_mqtt_publish >= MQTT_PUBLISH_INTERVAL:
                    self._publish_to_thingsboard(data)
                    self.last_mqtt_publish = now

                # Control de tasa de refresco con polling responsivo (cada 50ms)
                elapsed = time.time() - loop_start
                sleep_time = REFRESH_INTERVAL - elapsed
                if sleep_time > 0:
                    steps = int(sleep_time / 0.05)
                    for _ in range(steps):
                        if not self.running:
                            break
                        if self.btn_back and self.btn_back.value:
                            print("\n[APP] Botón Atrás presionado. Saliendo...")
                            self.running = False
                            break
                        if self.xbox:
                            evt = self.xbox.get_event(0.005)
                            while evt:
                                if evt[0] == 'btn' and evt[1] == self.xbox.B:
                                    print("\n[APP] Botón B presionado. Saliendo...")
                                    self.running = False
                                    break
                                evt = self.xbox.get_event(0.005)
                        time.sleep(0.05)

        except KeyboardInterrupt:
            print("\n[APP] Deteniendo...")
        finally:
            self.cleanup()

    @staticmethod
    def _distance(lat1, lon1, lat2, lon2):
        """Distancia aprox en grados (no precisa pero rápida)"""
        return ((lat1 - lat2) ** 2 + (lon1 - lon2) ** 2) ** 0.5

    def cleanup(self):
        """Limpia recursos"""
        print("[APP] Limpiando...")
        self.gps.stop()

        # Detener mando Xbox
        if hasattr(self, 'xbox') and self.xbox:
            try:
                self.xbox.stop()
                print("[GPS App] Mando Xbox detenido")
            except:
                pass

        # Desconectar MQTT
        if hasattr(self, 'mqtt_client') and self.mqtt_client:
            try:
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
                print("[MQTT] Desconectado de ThingsBoard")
            except:
                pass

        # Apagar pantallas via daemon
        if hasattr(self, 'fb') and self.fb:
            self.fb.blank()
            self.fb.update()
            self.fb.close()
            print("[APP] Pantallas apagadas")

        print("[APP] Aplicacion terminada.")


# ═══════════════════════════════════════════════════════
#  PUNTO DE ENTRADA
# ═══════════════════════════════════════════════════════
if __name__ == "__main__":
    import traceback
    try:
        app = GPSDisplayApp()
        app.start()
    except Exception:
        print("=" * 45)
        print("  [GPS App] ERROR FATAL AL INICIAR")
        print("=" * 45)
        traceback.print_exc()
        # Intentar mostrar el error en pantalla, si el framebuffer llego
        # a inicializarse antes del fallo.
        try:
            from fb_display import FbDisplay
            from PIL import ImageFont
            fb = FbDisplay(3)
            fb.blank()
            draw = fb.draw()
            draw.text((10, 10), "GPS App crasheo al iniciar", font=fb.font, fill=(255, 60, 60))
            draw.text((10, 40), "Revisa la consola / journalctl", font=fb.font_s, fill=(200, 200, 200))
            fb.update()
        except Exception:
            pass
        raise
