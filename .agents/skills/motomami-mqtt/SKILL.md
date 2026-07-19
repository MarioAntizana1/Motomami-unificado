---
name: motomami-mqtt
description: "MQTT telemetry para Raspberry Pi: paho.mqtt, ThingsBoard cloud, payload GPS+sistema, TelemetriaService thread, reconnection handling."
risk: safe
source: personal
date_added: "2026-07-17"
---

# MotoMami MQTT — ThingsBoard + Mosquitto

## Purpose

Guía para el sistema de telemetría MQTT: publicación periódica de GPS + métricas del sistema a ThingsBoard, y el patrón service thread con reconexión automática.

## Use this when

- Modificar `src/core/telemetria_service.py`
- Cambiar el payload de telemetría
- Configurar ThingsBoard o Mosquitto
- Debuggear conexión MQTT
- Añadir nuevos topics o brokers

## Architecture

```
SystemState (GPS + metrics)
  → TelemetriaService thread (cada 5s)
    → paho.mqtt.Client
      → ThingsBoard cloud (mqtt.thingsboard.cloud:1883)
        → v1/devices/me/telemetry
```

También se publica a un broker Mosquitto local en el legacy `final/`:
```
moto/gps/data      (GPS JSON)
moto/gps/status    ("connected"/"disconnected")
```

## Configuración (`config.ini`)

```ini
[thingsboard]
host = mqtt.thingsboard.cloud
token = <TU_TOKEN_DEVICE>
publish_interval = 5
```

El token se obtiene del panel de ThingsBoard → Devices → Credentials.

## API — `TelemetriaService`

`src/core/telemetria_service.py`:

```python
class TelemetriaService(threading.Thread):
    def __init__(self, state: SystemState):
        super().__init__(daemon=True)
        self._state = state
        self._client: mqtt.Client | None = None
        self._connected = False

    def run(self):
        self._connect()
        while not self._state.shutdown_event.is_set():
            if not self._connected:
                self._connect()  # reintentar
            else:
                self.publish()
            time.sleep(TELEMETRY_INTERVAL)
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
```

## Conexión

```python
def _connect(self):
    self._client = mqtt.Client()
    self._client.username_pw_set(TB_TOKEN)
    self._client.on_connect = self._on_connect
    self._client.on_disconnect = self._on_disconnect
    self._client.connect_async(TB_HOST, 1883, keepalive=60)
    self._client.loop_start()

def _on_connect(self, client, userdata, flags, rc):
    self._connected = (rc == 0)
    # rc=0 success, 1=bad proto, 2=bad client, 3=server unavailable, 4=bad user/pass, 5=not auth

def _on_disconnect(self, client, userdata, rc):
    self._connected = False
    if rc != 0:
        # desconexión inesperada, se reintenta en el próximo ciclo
        pass
```

## Payload de Telemetría

```python
def publish(self, extra=None):
    payload = {}

    # GPS
    gps = self._state.get_gps()
    payload["gps"] = {
        "lat": gps.lat,
        "lon": gps.lon,
        "speed": gps.speed_kmh,
        "altitude": gps.altitude,
        "satellites": gps.num_satellites,
        "has_fix": gps.has_fix,
    }

    # Sistema
    metrics = self._state.get_metrics()
    payload["system"] = {
        "cpu_usage": metrics.cpu_percent,
        "ram_usage": metrics.ram_percent,
        "disk_usage": metrics.disk_percent,
        "cpu_temp_c": metrics.cpu_temp,
        "uptime_hours": metrics.uptime_hours,
        "ip": metrics.ip_address,
    }

    if extra:
        payload.update(extra)

    self._client.publish("v1/devices/me/telemetry", json.dumps(payload), qos=1)
```

## CosasBoard Setup

1. Crear device en ThingsBoard
2. Copiar token de acceso
3. Configurar dashboard con widgets (mapa, gauges, charts)
4. Los datos aparecen automáticamente cada `publish_interval` segundos

## Mosquitto Local (legacy)

```python
# Publicación a broker local
client_local = mqtt.Client()
client_local.connect("localhost", 1883, 60)

# GPS data
client_local.publish("moto/gps/data", json.dumps({
    "lat": lat, "lon": lon, "speed": speed,
    "altitude": alt, "satellites": sats
}))

# Status
client_local.publish("moto/gps/status", "connected")
```

## Debugging

```bash
# Escuchar todos los topics del broker local
mosquitto_sub -h localhost -t "moto/#" -v

# Verificar conectividad ThingsBoard
mosquitto_sub -h mqtt.thingsboard.cloud -t "v1/devices/me/telemetry" -u "<TOKEN>"

# Probar conexión con cliente MQTT genérico
mosquitto_pub -h mqtt.thingsboard.cloud -t "v1/devices/me/telemetry" \
  -u "<TOKEN>" -m '{"test": 123}' -d
```

**Problemas comunes**:  
- `Connection refused` → ThingsBoard caído o token inválido
- Payload vacío en dashboard → formato JSON incorrecto
- Reconexión lenta → ajustar `keepalive` y `publish_interval`
- `loop_start()` ya corriendo → llamar solo una vez en `_connect()`

## Key Files

| File | Role |
|------|------|
| `src/core/telemetria_service.py` | Service thread MQTT |
| `src/config_loader.py` | Config: `TB_HOST`, `TB_TOKEN`, `EMQX_*` |
| `config.ini.example` | Template de configuración |
| `final/src/libs/telemetria.py` | Legacy: ThingsBoard + EMQX |
| `final/src/apps/gps_daemon.py` | Legacy: ThingsBoard + Mosquitto local |
