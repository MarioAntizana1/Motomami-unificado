"#!/usr/bin/env python3
"""
gps_daemon.py - Daemon GPS + Telemetria (SIN PANTALLA)
======================================================
Se ejecuta en background desde main.py.

Funciones:
  - Lee GPS del SIM7600-G via comandos AT
  - Publica datos GPS + sistema (CPU, RAM, temp) a ThingsBoard via MQTT
  - Publica datos tambien en MQTT local (Mosquitto) para la app de display
  - Se reconecta automaticamente si el SIM7600 se desconecta

Topics MQTT locales:
  moto/gps/data     -> JSON con datos GPS
  moto/gps/status   -> "connected" / "disconnected"

NO USA PANTALLAS NI GPIO DE DISPLAY.
"""

import os
import sys
import time
import json
import subprocess
import threading

# Asegurar rutas
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_BASE_DIR = os.path.dirname(_THIS_DIR)
for _p in [os.path.join(_BASE_DIR, 'lib'), os.path.join(_BASE_DIR, 'drivers')]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import psutil

try:
    import paho.mqtt.client as mqtt
    HAS_MQTT = True
except ImportError:
    HAS_MQTT = False
    print("[Daemon] paho-mqtt no instalado. Telemetria desactivada.")

from sim7600_gps import SIM7600GPS, SIM7600GPSData

# ==========================================================================
# CONFIGURACION
# ==========================================================================

GPS_AT_PORT = "/dev/ttyUSB2"
GPS_BAUD = 115200

# ThingsBoard
THINGSBOARD_HOST = "mqtt.thingsboard.cloud"
THINGSBOARD_PORT = 1883
THINGSBOARD_TOKEN = "YOUR_THINGSBOARD_TOKEN"

# MQTT Local (Mosquitto en la RPi)
LOCAL_MQTT_HOST = "localhost"
LOCAL_MQTT_PORT = 1883

# Intervalos
GPS_POLL_INTERVAL = 2.0       # Leer GPS cada 2 seg
MQTT_PUBLISH_INTERVAL = 10.0  # Publicar a ThingsBoard cada 10 seg
USB_CHECK_INTERVAL = 5.0      # Verificar USB cada 5 seg

# Deteccion USB
SIM7600_VENDOR = "1e0e"
SIM7600_PRODUCT = "9001"


# ==========================================================================
# DAEMON
# ==========================================================================

class GPSDaemon:
    def __init__(self):
        self.running = False
        self.gps = None
        self.last_data = SIM7600GPSData()
        self.sim7600_connected = False
        self.last_usb_check = 0
        self.last_mqtt_publish = 0
        self.mqtt_tb = None
        self.mqtt_local = None
        self.data_lock = threading.Lock()

        # Inicializar GPS
        self.gps = SIM7600GPS(
            at_port=GPS_AT_PORT,
            baudrate=GPS_BAUD,
            auto_start=False
        )
        self.gps.set_callback(self._on_gps_update)

        # MQTT
        if HAS_MQTT:
            self._init_mqtt()

    def _init_mqtt(self):
        """Conectar a ThingsBoard y MQTT local."""
        try:
            self.mqtt_tb = mqtt.Client()
            self.mqtt_tb.username_pw_set(THINGSBOARD_TOKEN)
            self.mqtt_tb.connect(THINGSBOARD_HOST, THINGSBOARD_PORT, 60)
            self.mqtt_tb.loop_start()
            print(f"[Daemon] MQTT ThingsBoard conectado")
        except Exception as e:
            print(f"[Daemon] Error ThingsBoard: {e}")
            self.mqtt_tb = None

        try:
            self.mqtt_local = mqtt.Client()
            self.mqtt_local.connect(LOCAL_MQTT_HOST, LOCAL_MQTT_PORT, 60)
            self.mqtt_local.loop_start()
            print(f"[Daemon] MQTT Local conectado")
        except Exception as e:
            print(f"[Daemon] Error MQTT Local: {e}")
            self.mqtt_local = None

    def _on_gps_update(self, data):
        with self.data_lock:
            self.last_data = data

    @staticmethod
    def _check_sim7600_usb():
        """Verifica si el SIM7600-G esta conectado por USB."""
        try:
            result = subprocess.run(
                ["lsusb"], capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if SIM7600_VENDOR in line.lower() and SIM7600_PRODUCT in line.lower():
                        return True
        except Exception:
            pass
        return False

    def _get_system_telemetry(self):
        """Recolecta metricas del sistema."""
        return {
            "cpu": psutil.cpu_percent(interval=0.1),
            "ram": psutil.virtual_memory().percent,
            "cpu_temp": psutil.sensors_temperatures().get("cpu_thermal", [None])[0] if
                        hasattr(psutil, 'sensors_temperatures') else 0,
            "uptime": int(time.time() - psutil.boot_time()) if
                      hasattr(psutil, 'boot_time') else 0,
        }

    def _publish_gps_local(self):
        """Publica datos GPS en MQTT local."""
        if not self.mqtt_local:
            return

        with self.data_lock:
            data = self.last_data
            lat, lon = data.get_coordinates_decimal()

        payload = json.dumps({
            "latitude": lat,
            "longitude": lon,
            "speed_kmh": data.speed_kmh,
            "altitude": data.altitude,
            "track_angle": data.track_angle,
            "num_satellites": data.num_satellites,
            "has_fix": data.has_fix,
            "gps_time": data.time,
            "gps_date": data.date,
            "timestamp": time.time(),
        })

        try:
            self.mqtt_local.publish("moto/gps/data", payload, qos=0)
            self.mqtt_local.publish("moto/gps/status",
                                    "connected" if self.sim7600_connected else "disconnected",
                                    qos=0)
        except Exception:
            pass

    def _publish_to_thingsboard(self):
        """Publica GPS + telemetria a ThingsBoard."""
        if not self.mqtt_tb:
            return

        with self.data_lock:
            data = self.last_data
            lat, lon = data.get_coordinates_decimal()

        sys_telemetry = self._get_system_telemetry()

        payload = {
            "latitude": lat,
            "longitude": lon,
            "altitude": data.altitude,
            "speed": data.speed_kmh,
            "track_angle": data.track_angle,
            "num_satellites": data.num_satellites,
            "has_fix": 1 if data.has_fix else 0,
            "gps_time_utc": data.time,
            "gps_date": data.date,
            **sys_telemetry,
        }

        try:
            self.mqtt_tb.publish(
                "v1/devices/me/telemetry",
                json.dumps(payload),
                qos=0
            )
        except Exception as e:
            print(f"[Daemon] Error publicando TB: {e}")

    def run(self):
        self.running = True
        print("[Daemon] Iniciado. Esperando SIM7600-G...")

        try:
            while self.running:
                now = time.time()

                # Verificar USB
                if now - self.last_usb_check >= USB_CHECK_INTERVAL:
                    was_connected = self.sim7600_connected
                    self.sim7600_connected = self._check_sim7600_usb()

                    if self.sim7600_connected and not was_connected:
                        print("[Daemon] SIM7600-G CONECTADO. Iniciando GPS...")
                        self.gps.start()
                        # Publicar status
                        if self.mqtt_local:
                            self.mqtt_local.publish("moto/gps/status", "connected", qos=0)

                    elif not self.sim7600_connected and was_connected:
                        print("[Daemon] SIM7600-G DESCONECTADO. Deteniendo GPS...")
                        self.gps.stop()
                        if self.mqtt_local:
                            self.mqtt_local.publish("moto/gps/status", "disconnected", qos=0)

                    self.last_usb_check = now

                # Publicar MQTT local (GPS)
                self._publish_gps_local()

                # Publicar a ThingsBoard
                if now - self.last_mqtt_publish >= MQTT_PUBLISH_INTERVAL:
                    if self.sim7600_connected:
                        self._publish_to_thingsboard()
                    self.last_mqtt_publish = now

                time.sleep(1)

        except KeyboardInterrupt:
            print("\n[Daemon] Deteniendo...")
        finally:
            self.gps.stop()
            if self.mqtt_tb:
                self.mqtt_tb.loop_stop()
                self.mqtt_tb.disconnect()
            if self.mqtt_local:
                self.mqtt_local.loop_stop()
                self.mqtt_local.disconnect()
            print("[Daemon] Apagado.")


if __name__ == '__main__':
    daemon = GPSDaemon()
    daemon.run()
"