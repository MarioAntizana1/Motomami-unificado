# -*- coding: utf-8 -*-
"""
telemetria.py - Publicación de telemetría a ThingsBoard + EMQX Cloud con interfaz gráfica

Uso como módulo (desde otra app):
    from telemetria import Telemetria
    t = Telemetria()
    t.start()
    ...
    t.stop()

Uso standalone:
    cd src && sudo python3 lib/telemetria.py
"""

import time
import json
import os
import sys
import socket

# ── Asegurar ruta al driver ──
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_BASE_DIR = os.path.dirname(_THIS_DIR)  # src/
_DRIVERS = os.path.join(_BASE_DIR, 'drivers')
if _DRIVERS not in sys.path:
    sys.path.insert(0, _DRIVERS)

import psutil
import board
import digitalio
from PIL import Image, ImageDraw, ImageFont
from fb_display import FbDisplay, daemon_available

# Control Xbox opcional
try:
    from vp_controller import XboxController
    HAS_XBOX = True
except ImportError:
    HAS_XBOX = False

try:
    import paho.mqtt.client as mqtt
    HAS_MQTT = True
except ImportError:
    HAS_MQTT = False
    print("[Telemetria] paho-mqtt no instalado. La telemetria estara desactivada.")
    print("           Instala con: sudo pip3 install paho-mqtt")


# ═══════════════════════════════════════════════════════
#  CONFIGURACIÓN
# ═══════════════════════════════════════════════════════

# ThingsBoard
THINGSBOARD_HOST = 'mqtt.thingsboard.cloud'
ACCESS_TOKEN = 'YOUR_THINGSBOARD_ACCESS_TOKEN'

# EMQX Cloud
EMQX_HOST = 'your-emqx-broker.emqxsl.com'
EMQX_PORT = 8883
EMQX_USERNAME = 'your_emqx_username'
EMQX_PASSWORD = 'YOUR_EMQX_PASSWORD'
EMQX_CLIENT_ID = 'raspi_telemetria'

PUBLISH_INTERVAL = 5  # segundos entre publicaciones


class Telemetria:
    """Publica telemetría del sistema en ThingsBoard y EMQX Cloud con soporte de pantalla."""

    def __init__(self, publish_interval: int = PUBLISH_INTERVAL, use_display: bool = True):
        self.interval = publish_interval
        self._running = False
        self._client_tb = None
        self._client_emqx = None
        self.use_display = use_display
        self.pub_count = 0
        self.start_time = time.time()
        
        self.display_sys = None    # Flag: display #1 (left) available
        self.display_net = None    # Flag: display #2 (right) available
        self.fb = None             # FbDisplay canvas

        # Botón físico (GPIO 16)
        try:
            self.btn_back = digitalio.DigitalInOut(board.D16)
            self.btn_back.direction = digitalio.Direction.INPUT
            self.btn_back.pull = digitalio.Pull.DOWN
        except Exception:
            self.btn_back = None

        # Mando Xbox
        self.xbox = XboxController() if HAS_XBOX else None
        if self.xbox and self.xbox.connect():
            self.xbox.start()
            print("[Telemetria] Mando Xbox conectado para salir (botón B)")
        else:
            self.xbox = None

    # Conexiones MQTT

    def _connect_thingsboard(self):
        """Conecta a ThingsBoard (MQTT simple, sin TLS)."""
        try:
            if not HAS_MQTT:
                print("[Telemetria] ThingsBoard: desactivado (paho-mqtt no instalado)")
                return None
            client = mqtt.Client()
            client.username_pw_set(ACCESS_TOKEN)
            client.connect(THINGSBOARD_HOST, 1883, 60)
            client.loop_start()
            print(f"[Telemetria] ThingsBoard conectado ({ACCESS_TOKEN[:8]}...)")
            return client
        except Exception as e:
            print(f"[Telemetria] Error ThingsBoard: {e}")
            return None

    def _connect_emqx(self):
        """Conecta a EMQX Cloud (MQTT over TLS/SSL)."""
        try:
            if not HAS_MQTT:
                print("[Telemetria] EMQX: desactivado (paho-mqtt no instalado)")
                return None
            client = mqtt.Client(client_id=EMQX_CLIENT_ID)
            client.username_pw_set(EMQX_USERNAME, EMQX_PASSWORD)
            client.tls_set(ca_certs="/etc/ssl/certs/ca-certificates.crt")
            client.on_connect = self._on_connect_emqx
            client.connect(EMQX_HOST, EMQX_PORT, 60)
            client.loop_start()
            return client
        except Exception as e:
            print(f"[Telemetria] Error EMQX: {e}")
            return None

    @staticmethod
    def _on_connect_emqx(client, userdata, flags, rc):
        status = {
            0: "Conectado exitosamente",
            1: "Protocol version incorrecto",
            2: "Client ID rechazado",
            3: "Servidor no disponible",
            4: "Usuario/password incorrectos",
            5: "No autorizado",
        }
        print(f"[EMQX] {status.get(rc, f'Codigo {rc}')}")

    # Telemetría del sistema

    @staticmethod
    def get_telemetry() -> dict:
        """Recolecta métricas del sistema RPi."""
        data = {}

        # CPU
        cpu = psutil.cpu_percent(percpu=True)
        if len(cpu) == 1:
            data['cpu'] = cpu[0]
        else:
            data.update({f'cpu{i}': c for i, c in enumerate(cpu)})

        # Temperatura
        if hasattr(psutil, "sensors_temperatures"):
            for name, entries in psutil.sensors_temperatures().items():
                for i, e in enumerate(entries):
                    data[e.label or f"{name}_{i}"] = round(e.current, 1)

        # RAM y Disco
        data['ram'] = round(psutil.virtual_memory().percent, 1)
        data['disk'] = round(psutil.disk_usage('/').percent, 1)

        return data

    # Publicación

    def publish(self, data: dict = None):
        """Publica telemetría en ambos brokers."""
        if data is None:
            data = self.get_telemetry()

        payload = json.dumps(data)
        success = False

        if self._client_tb:
            try:
                result = self._client_tb.publish('v1/devices/me/telemetry', payload)
                if result.rc == 0:
                    success = True
                print(f"[ThingsBoard] rc={result.rc} | {list(data.keys())}")
            except Exception as e:
                print(f"[ThingsBoard] Error: {e}")

        if self._client_emqx:
            try:
                result = self._client_emqx.publish('v1/devices/me/telemetry', payload)
                if result.rc == 0:
                    success = True
                print(f"[EMQX] rc={result.rc} | {list(data.keys())}")
            except Exception as e:
                print(f"[EMQX] Error: {e}")

        if success:
            self.pub_count += 1

    # Métodos gráficos de Pantalla

    def _init_displays(self):
        """Inicializa displays via daemon de framebuffer."""
        if not self.use_display:
            return

        self.fb = FbDisplay(3)  # Canvas 640x240
        if not daemon_available():
            print("[Telemetria] ADVERTENCIA: fb_daemon no detectado!")
            self.fb = None
            return

        self.display_sys = True
        self.display_net = True
        print("[Telemetria] Displays via daemon FB (640x240 canvas)")

    def _render_and_display(self, data: dict):
        """Renderiza y dibuja las métricas en las pantallas."""
        # --- Pantalla 1: Sistema (Horizontal 320x240) ---
        img_sys = None
        if self.display_sys:
            W, H = 320, 240
            img_sys = Image.new("RGB", (W, H), (10, 10, 25))
            draw = ImageDraw.Draw(img_sys)
            
            try:
                font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
                font_normal = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
                font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10)
            except:
                font_title = font_normal = font_small = ImageFont.load_default()
            
            # Título
            draw.text((10, 5), "SISTEMA - MotoMami", font=font_title, fill=(0, 200, 255))
            draw.line([(0, 25), (W, 25)], fill=(40, 40, 80), width=1)
            
            # CPU average
            cpu_val = data.get('cpu', 0.0)
            if 'cpu' not in data:
                cpus = [v for k, v in data.items() if k.startswith('cpu') and k != 'cpu']
                if cpus:
                    cpu_val = sum(cpus) / len(cpus)
            
            # Dibujar CPU
            draw.text((10, 35), f"CPU: {cpu_val:.1f}%", font=font_normal, fill=(255, 255, 255))
            draw.rectangle([100, 37, 280, 47], fill=(30, 30, 60))
            draw.rectangle([100, 37, 100 + int(180 * cpu_val / 100), 47], fill=(0, 255, 100) if cpu_val < 80 else (255, 0, 0))
            
            # Dibujar RAM
            ram_val = data.get('ram', 0.0)
            draw.text((10, 65), f"RAM: {ram_val:.1f}%", font=font_normal, fill=(255, 255, 255))
            draw.rectangle([100, 67, 280, 77], fill=(30, 30, 60))
            draw.rectangle([100, 67, 100 + int(180 * ram_val / 100), 77], fill=(0, 200, 255))
            
            # Dibujar Disco
            disk_val = data.get('disk', 0.0)
            draw.text((10, 95), f"DISCO: {disk_val:.1f}%", font=font_normal, fill=(255, 255, 255))
            draw.rectangle([100, 97, 280, 107], fill=(30, 30, 60))
            draw.rectangle([100, 97, 100 + int(180 * disk_val / 100), 107], fill=(255, 200, 0))
            
            # Temperatura de CPU
            temp_val = data.get('cpu_thermal_0', data.get('cpu_thermal', 0.0))
            if temp_val == 0.0:
                for k, v in data.items():
                    if 'temp' in k or 'thermal' in k:
                        temp_val = v
                        break
            draw.text((10, 130), f"CPU Temp: {temp_val:.1f} °C", font=font_normal, fill=(255, 100, 100) if temp_val > 60 else (0, 255, 200))
            
            # Uptime
            uptime_s = time.time() - self.start_time
            hours = int(uptime_s // 3600)
            minutes = int((uptime_s % 3600) // 60)
            seconds = int(uptime_s % 60)
            draw.text((10, 160), f"Uptime: {hours:02d}:{minutes:02d}:{seconds:02d}", font=font_normal, fill=(200, 200, 200))
            
            # Instrucciones
            draw.rectangle([0, H - 20, W, H], fill=(0, 0, 40))
            draw.text((10, H - 18), "B / ATRAS = Volver al menu", font=font_small, fill=(255, 255, 0))
            
            # img_sys is ready, will be pushed to canvas below

        # --- Pantalla 2: Red y Conectividad (Horizontal 320x240) ---
        img_net = None
        if self.display_net:
            W, H = 320, 240
            img_net = Image.new("RGB", (W, H), (5, 15, 10))
            draw = ImageDraw.Draw(img_net)
            
            try:
                font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
                font_normal = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
                font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10)
            except:
                font_title = font_normal = font_small = ImageFont.load_default()
            
            # Título
            draw.text((10, 5), "RED & BROKERS", font=font_title, fill=(0, 255, 100))
            draw.line([(0, 25), (W, 25)], fill=(30, 60, 40), width=1)
            
            # IP local
            ip = self._get_ip_address()
            draw.text((10, 40), f"IP Local: {ip}", font=font_normal, fill=(255, 255, 255))
            
            # ThingsBoard status
            tb_ok = self._client_tb is not None
            tb_txt = "CONECTADO" if tb_ok else "DESCONECTADO"
            tb_col = (0, 255, 0) if tb_ok else (255, 50, 50)
            draw.text((10, 70), "ThingsBoard:", font=font_normal, fill=(200, 200, 200))
            draw.text((120, 70), tb_txt, font=font_normal, fill=tb_col)
            
            # EMQX status
            emqx_ok = self._client_emqx is not None
            emqx_txt = "CONECTADO" if emqx_ok else "DESCONECTADO"
            emqx_col = (0, 255, 0) if emqx_ok else (255, 50, 50)
            draw.text((10, 100), "EMQX Cloud:", font=font_normal, fill=(200, 200, 200))
            draw.text((120, 100), emqx_txt, font=font_normal, fill=emqx_col)
            
            # Publicaciones
            draw.text((10, 140), f"Publicaciones OK: {self.pub_count}", font=font_normal, fill=(255, 200, 0))
            
            # Broker config info
            draw.text((10, 170), f"Frecuencia envio: cada {self.interval}s", font=font_small, fill=(150, 180, 160))
            
            # img_net is ready, will be pushed to canvas below

        # Push both images to the fb daemon
        if self.fb:
            full = self.fb.image()
            if img_sys:
                full.paste(img_sys, (0, 0))
            if img_net:
                full.paste(img_net, (320, 0))
            self.fb.update()

    @staticmethod
    def _get_ip_address() -> str:
        """Obtiene la IP local del dispositivo."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    # Ciclo de vida

    def start(self):
        """Inicia las conexiones MQTT y el loop de publicación."""
        self._client_tb = self._connect_thingsboard()
        self._client_emqx = self._connect_emqx()
        self._init_displays()
        self._running = True
        self.start_time = time.time()

        print(f"[Telemetria] Publicando cada {self.interval}s. Ctrl+C para salir.")
        
        last_publish_time = 0
        last_screen_time = 0

        try:
            while self._running:
                now = time.time()

                # Verificar botón físico de retroceso (GPIO 16)
                if self.btn_back and self.btn_back.value:
                    print("\n[Telemetria] Botón Atrás presionado. Saliendo...")
                    self._running = False
                    break

                # Verificar botón B del mando Xbox
                if self.xbox:
                    evt = self.xbox.get_event(0.005)
                    while evt:
                        if evt[0] == 'btn' and evt[1] == self.xbox.B:
                            print("\n[Telemetria] Botón B presionado. Saliendo...")
                            self._running = False
                            break
                        evt = self.xbox.get_event(0.005)
                    if not self._running:
                        break

                # Publicar periódicamente
                if now - last_publish_time >= self.interval:
                    self.publish()
                    last_publish_time = now

                # Actualizar pantallas periódicamente (cada 1s)
                if self.use_display and (now - last_screen_time >= 1.0):
                    data = self.get_telemetry()
                    self._render_and_display(data)
                    last_screen_time = now

                time.sleep(0.05)

        except KeyboardInterrupt:
            print("\n[Telemetria] Interrumpido.")
        finally:
            self.stop()

    def stop(self):
        """Detiene las conexiones MQTT y limpia recursos."""
        self._running = False
        
        # Desconectar brokers
        for client, name in [(self._client_tb, "ThingsBoard"),
                              (self._client_emqx, "EMQX")]:
            if client:
                try:
                    client.loop_stop()
                    client.disconnect()
                    print(f"[Telemetria] {name} desconectado")
                except Exception:
                    pass
        self._client_tb = None
        self._client_emqx = None

        # Detener mando Xbox
        if hasattr(self, 'xbox') and self.xbox:
            try:
                self.xbox.stop()
                print("[Telemetria] Mando Xbox detenido")
            except:
                pass

        # Apagar pantallas via daemon
        if hasattr(self, 'fb') and self.fb:
            try:
                self.fb.blank()
                self.fb.update()
                self.fb.close()
                print("[Telemetria] Pantallas apagadas")
            except Exception as e:
                print(f"[Telemetria] Error apagando pantallas: {e}")


# ═══════════════════════════════════════════════════════
if __name__ == "__main__":
    t = Telemetria(use_display=True)
    t.start()
