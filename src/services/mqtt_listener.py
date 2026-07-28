"""
mqtt_listener.py - Escucha los topics MQTT locales (Mosquitto)
y actualiza el estado de los ESP32 (velocímetro + direccionales).
"""
import json
import threading
import time
import os
import sys

_SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
if os.path.join(_SRC, "core") not in sys.path:
    sys.path.insert(0, os.path.join(_SRC, "core"))

from config_loader import MQTT_LOCAL_HOST, MQTT_LOCAL_PORT

try:
    import paho.mqtt.client as mqtt
    _HAS_MQTT = True
except ImportError:
    _HAS_MQTT = False


class MqttListenerService(threading.Thread):
    """
    Hilo daemon que se suscribe al Mosquitto local y parsea los mensajes
    de los ESP32, actualizando SystemState.esp32_velocimetro y .esp32_direccionales.
    """

    def __init__(self, state=None):
        super().__init__(name="MqttListener", daemon=True)
        self._state = state
        self._client = None
        self._stop_event = threading.Event()
        self._connected = False

    def run(self):
        if not _HAS_MQTT:
            print("[MQTT-Listener] paho-mqtt no instalado. Desactivado.")
            return

        while not self._stop_event.is_set():
            try:
                self._connect_and_listen()
            except Exception as e:
                print(f"[MQTT-Listener] Error: {e}")
                self._stop_event.wait(timeout=5)

    def _connect_and_listen(self):
        self._client = mqtt.Client()
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.on_disconnect = self._on_disconnect

        print(f"[MQTT-Listener] Conectando a {MQTT_LOCAL_HOST}:{MQTT_LOCAL_PORT}...")
        self._client.connect(MQTT_LOCAL_HOST, MQTT_LOCAL_PORT, 60)
        self._client.subscribe("motomami/#", qos=1)
        self._client.subscribe("motomami-input/#", qos=1)

        while not self._stop_event.is_set():
            self._client.loop(timeout=0.5)

    def stop(self):
        print("[MQTT-Listener] Deteniendo...")
        self._stop_event.set()
        if self._client:
            try:
                self._client.disconnect()
            except Exception:
                pass

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ── Callbacks MQTT ──

    def _on_connect(self, client, userdata, flags, rc):
        self._connected = (rc == 0)
        if rc == 0:
            print(f"[MQTT-Listener] Conectado a Mosquitto en {MQTT_LOCAL_HOST}")
            client.subscribe("motomami/#", qos=1)
            client.subscribe("motomami-input/#", qos=1)
        else:
            print(f"[MQTT-Listener] Error conexión (rc={rc})")

    def _on_disconnect(self, client, userdata, rc):
        self._connected = False
        if rc != 0:
            print(f"[MQTT-Listener] Desconectado (rc={rc}), reintentará...")

    def _on_message(self, client, userdata, msg):
        if self._state is None:
            return
        topic = msg.topic
        payload = self._strip_msg_id(msg.payload.decode(errors="replace").strip())

        # ── Velocímetro ──
        if topic == "motomami/velocimetro/data":
            self._handle_velo_data(payload)
        elif topic == "motomami/velocimetro/odometro":
            self._handle_velo_odometro(payload)
        elif topic == "motomami/velocimetro/status":
            self._state.update_esp32_velocimetro(online=(payload.lower() == "online"))
        elif topic == "motomami/velocimetro/ip":
            self._state.update_esp32_velocimetro(ip=payload)
        elif topic == "motomami/velocimetro/rssi":
            self._state.update_esp32_velocimetro(rssi=payload)
        elif topic == "motomami/velocimetro/id":
            self._state.update_esp32_velocimetro(id=payload)

        # ── Direccionales ──
        elif topic == "motomami/status":
            self._state.update_esp32_direccionales(online=(payload.lower() == "online"))
        elif topic == "motomami/status/ip":
            self._state.update_esp32_direccionales(ip=payload)
        elif topic == "motomami/status/rssi":
            self._state.update_esp32_direccionales(rssi=payload)
        elif topic == "motomami/status/id":
            self._state.update_esp32_direccionales(id=payload)
        elif topic == "motomami/frenado":
            self._state.update_esp32_direccionales(frenado=(payload == "ON"))
        elif topic == "motomami/luz_nocturna":
            self._state.update_esp32_direccionales(luz_nocturna=(payload == "ON"))
        elif topic == "motomami/luz_nocturna/intensidad":
            self._handle_intensidad(payload, "intensidad_nocturna")
        elif topic == "motomami/intensidad":
            self._handle_intensidad(payload, "intensidad")
        elif topic == "motomami/intermitente_izquierda":
            self._state.update_esp32_direccionales(intermitente_der=(payload == "ON"))
        elif topic == "motomami/intermitente_derecha":
            self._state.update_esp32_direccionales(intermitente_izq=(payload == "ON"))
        elif topic == "motomami/intermitente_emergencia":
            self._state.update_esp32_direccionales(emergencia=(payload == "ON"))

        # ── Input ──
        elif topic == "motomami-input/status":
            self._state.update_esp32_input(online=(payload.lower() == "online"))
        elif topic == "motomami-input/status/ip":
            self._state.update_esp32_input(ip=payload)
        elif topic == "motomami-input/status/rssi":
            self._state.update_esp32_input(rssi=payload)
        elif topic == "motomami-input/status/id":
            self._state.update_esp32_input(id=payload)
        elif topic == "motomami-input/data":
            self._handle_input_data(payload)

    def _handle_input_data(self, payload: str):
        """Parse 'LLLLL' (LEFT,RIGHT,EMERG,BRAKE,NIGHT) del topic motomami-input/data.
        GPIO con pull-up: '0' = presionado (LOW), '1' = liberado (HIGH)."""
        if len(payload) < 5:
            return
        self._state.update_esp32_input(
            left=(payload[0] == "0"),
            right=(payload[1] == "0"),
            emerg=(payload[2] == "0"),
            brake=(payload[3] == "0"),
            night=(payload[4] == "0"),
        )

    @staticmethod
    def _strip_msg_id(payload: str) -> str:
        """El módulo input publica '<id>:ON' / '<id>:OFF' (id = contador de
        mensajes para detectar pérdidas). Acepta también el formato plano
        'ON'/'OFF' de antes."""
        head, sep, tail = payload.partition(":")
        if sep and head.isdigit() and tail:
            return tail
        return payload

    def _handle_velo_data(self, payload: str):
        try:
            data = json.loads(payload)
            kwargs = dict(
                speed=float(data.get("s", 0)),
                distance=float(data.get("d", 0)),
                pulses=int(data.get("p", 0)),
                online=True,
            )
            raw_id = data.get("id")
            if raw_id is not None:
                kwargs["id"] = str(raw_id)
            self._state.update_esp32_velocimetro(**kwargs)
        except (json.JSONDecodeError, ValueError):
            pass

    def _handle_velo_odometro(self, payload: str):
        try:
            self._state.update_esp32_velocimetro(odometro=float(payload))
        except ValueError:
            pass

    def _handle_intensidad(self, payload: str, field: str):
        try:
            val = int(payload)
            self._state.update_esp32_direccionales(**{field: val})
        except ValueError:
            pass
