"""
telemetria_service.py - Servicio de telemetría siempre activo.
Corre en un hilo background y publica a ThingsBoard cada N segundos.
"""
import threading
import time
import json
import os
import sys
import socket

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config_loader import TB_HOST, TB_TOKEN, TB_PUBLISH_INTERVAL, TELEMETRY_INTERVAL

try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False

try:
    import paho.mqtt.client as mqtt
    _HAS_MQTT = True
except ImportError:
    _HAS_MQTT = False


class TelemetriaService(threading.Thread):
    """
    Hilo daemon que publica telemetría del sistema a ThingsBoard.
    - Publica cada TELEMETRY_INTERVAL segundos (configurable en config.ini)
    - Incluye datos GPS si el GPSService los provee
    - Thread-safe: lee estado global de SystemState
    """

    def __init__(self, state=None):
        super().__init__(name="TelemetriaService", daemon=True)
        self._state = state  # SystemState (opcional)
        self._client = None
        self._stop_event = threading.Event()
        self._pub_count = 0
        self._connected = False
        self._interval = TELEMETRY_INTERVAL

    # ── MQTT ──

    def _connect(self):
        if not _HAS_MQTT or not TB_TOKEN:
            print("[Telemetria] MQTT desactivado (paho-mqtt no instalado o token vacío)")
            return
        try:
            self._client = mqtt.Client()
            self._client.username_pw_set(TB_TOKEN)
            self._client.on_connect = self._on_connect
            self._client.on_disconnect = self._on_disconnect
            self._client.connect(TB_HOST, 1883, 60)
            self._client.loop_start()
        except Exception as e:
            print(f"[Telemetria] Error conectando MQTT: {e}")
            self._client = None

    def _on_connect(self, client, userdata, flags, rc):
        self._connected = (rc == 0)
        status = "OK" if rc == 0 else f"Error rc={rc}"
        tok_preview = TB_TOKEN[:4] + "****" if TB_TOKEN else "N/A"
        print(f"[Telemetria] ThingsBoard {status} (token={tok_preview})")

    def _on_disconnect(self, client, userdata, rc):
        self._connected = False
        if rc != 0:
            print(f"[Telemetria] Desconectado (rc={rc}), reintentando...")

    # ── Recolección ──

    @staticmethod
    def _collect_system() -> dict:
        data = {}
        if not _HAS_PSUTIL:
            return data
        try:
            data["cpu"] = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory()
            data["ram"] = round(mem.percent, 1)
            data["ram_used_mb"] = round(mem.used / 1024 / 1024, 0)
            disk = psutil.disk_usage("/")
            data["disk"] = round(disk.percent, 1)
            data["uptime"] = round(time.time() - psutil.boot_time(), 0)
            # Temperatura
            if hasattr(psutil, "sensors_temperatures"):
                temps = psutil.sensors_temperatures()
                for key in ("cpu_thermal", "coretemp"):
                    if key in temps and temps[key]:
                        data["cpu_temp"] = round(temps[key][0].current, 1)
                        break
            # IP
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                data["ip"] = s.getsockname()[0]
                s.close()
            except Exception:
                data["ip"] = "0.0.0.0"
        except Exception as e:
            print(f"[Telemetria] Error collect_system: {e}")
        return data

    def _collect_gps(self) -> dict:
        if self._state is None:
            return {}
        gps = self._state.get_gps()
        lat, lon = gps.get_display_coords()
        return {
            "latitude": lat,
            "longitude": lon,
            "altitude": gps.altitude,
            "speed_kmh": gps.speed_kmh,
            "track_angle": gps.track_angle,
            "satellites": gps.num_satellites,
            "gps_fix": 1 if gps.has_fix else 0,
            "gps_cached": 0 if (gps.has_fix and gps.lat != 0.0) else (1 if gps.cached_has_fix else 0),
            "gps_trip_distance_m": gps.gps_trip_distance_m,
            "gps_total_distance_m": gps.gps_total_distance_m,
        }

    def _collect_wheel(self) -> dict:
        if self._state is None:
            return {}
        wheel = self._state.get_esp32_velocimetro()
        return {
            "wheel_speed_kmh": wheel.speed,
            "wheel_distance_m": wheel.distance_m,
            "wheel_odometer_km": wheel.odometro,
            "wheel_pulses": wheel.pulses,
            "wheel_mqtt_online": 1 if wheel.online else 0,
        }

    # ── Publicación ──

    def publish(self, extra: dict = None):
        payload = {}
        payload.update(self._collect_system())
        payload.update(self._collect_gps())
        payload.update(self._collect_wheel())
        if extra:
            payload.update(extra)

        # Actualizar métricas en SystemState
        if self._state:
            self._state.update_metrics(
                cpu_percent=payload.get("cpu", 0),
                ram_percent=payload.get("ram", 0),
                disk_percent=payload.get("disk", 0),
                cpu_temp=payload.get("cpu_temp", 0),
            )

        if self._client and self._connected:
            try:
                result = self._client.publish(
                    "v1/devices/me/telemetry",
                    json.dumps(payload)
                )
                if result.rc == 0:
                    self._pub_count += 1
                    gps_str = f"Lat:{payload.get('latitude',0):.4f} Lon:{payload.get('longitude',0):.4f}" \
                              if payload.get("latitude") else "GPS:N/A"
                    print(f"[Telemetria] #{self._pub_count} CPU:{payload.get('cpu',0):.0f}% "
                          f"RAM:{payload.get('ram',0):.0f}% {gps_str}")
            except Exception as e:
                print(f"[Telemetria] Error publish: {e}")

    # ── Hilo ──

    def run(self):
        print(f"[Telemetria] Iniciando (intervalo={self._interval}s)")
        self._connect()

        # Warmup: esperar 1s para que psutil tenga datos de CPU
        time.sleep(1)

        last_pub = 0
        while not self._stop_event.is_set():
            now = time.time()
            if now - last_pub >= self._interval:
                self.publish()
                last_pub = now
            self._stop_event.wait(timeout=0.5)

    def stop(self):
        print("[Telemetria] Deteniendo...")
        self._stop_event.set()
        if self._client:
            try:
                self._client.loop_stop()
                self._client.disconnect()
            except Exception:
                pass
        print(f"[Telemetria] Detenido. Total publicaciones: {self._pub_count}")

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def pub_count(self) -> int:
        return self._pub_count
