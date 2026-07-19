---
name: motomami-gps
description: "Driver SIM7600 GPS para Raspberry Pi: AT commands, NMEA parsing, serial a /dev/ttyUSB2, GPSService thread, SystemState update."
risk: safe
source: personal
date_added: "2026-07-17"
---

# MotoMami GPS — SIM7600 AT Commands

## Purpose

Guía para trabajar con el módulo GPS del SIM7600G: inicialización, lectura de coordenadas vía AT commands, parsing NMEA, y el patrón service thread que alimenta `SystemState`.

## Use this when

- Modificar o debuggear `src/drivers/sim7600_gps.py`
- Cambiar la lógica de `src/core/gps_service.py`
- Añadir nuevos campos NMEA (altitud, satélites, velocidad)
- Debuggear conexión serial con el SIM7600

## Architecture

```
SIM7600G (hardware)
  → /dev/ttyUSB2 (AT port, 115200 baud)
    → SIM7600GPS (src/drivers/sim7600_gps.py)
      → callback on_gps_data(data)
        → GPSService (src/core/gps_service.py)
          → SystemState.update_gps(data)
```

## Hardware

- **Módulo**: SIM7600G-H (4G + GNSS)
- **AT port**: `/dev/ttyUSB2` (115200 baud, 8N1)
- **NMEA port**: `/dev/ttyUSB1` (raw NMEA sentences)
- **Conexión**: USB-to-serial (CH340 o similar), detectado como `ttyUSB*`

## Inicialización

Secuencia de AT commands (`sim7600_gps.py:_init_gps`):

```python
AT+CGPS=0              # Apagar GPS primero
AT+CGPSINFOCFG=1,31   # Configurar formato: 1=NMEA, 31=GGA+RMC+GSV+GSA+VTG
AT+CGPS=1              # Encender GPS
```

**Tiempo de first fix**: 30-60 segundos en cielo abierto, hasta 5 min en interiores.

## API Principal — `SIM7600GPS`

**Clase** en `src/drivers/sim7600_gps.py`:

```python
gps = SIM7600GPS(at_port="/dev/ttyUSB2", baudrate=115200, auto_start=True)
gps.set_callback(lambda data: print(data.latitude, data.longitude))
gps.start()
data = gps.get_data()  # thread-safe snapshot
# data.latitude, data.longitude, data.altitude, data.speed_kmh
# data.num_satellites, data.has_fix, data.gps_on
gps.stop()
```

## `SIM7600GPSData` Fields

| Field | Type | Descripción |
|-------|------|-------------|
| `latitude` | float | Latitud en formato NMEA (DDMM.MMMM) |
| `longitude` | float | Longitud en formato NMEA (DDDMM.MMMM) |
| `lat_direction` | str | 'N' o 'S' |
| `lon_direction` | str | 'E' o 'W' |
| `altitude` | float | Metros sobre nivel del mar |
| `speed_kmh` | float | Velocidad en km/h |
| `track_angle` | float | Ángulo de rumbo (grados) |
| `has_fix` | bool | Fix válido |
| `num_satellites` | int | Satélites visibles |
| `received_at` | float | timestamp (`time.time()`) |

```python
# Conversión a decimal
lat, lon = data.get_coordinates_decimal()
```

## NMEA Parsing

El driver parsea `AT+CGPSINFO` response (formato GGA extendido) con regex:

```python
_GPSCGPS_RE = re.compile(
    r"\+CGPSINFO:\s*"                                # header
    r"(\d{4}\.\d+|)\s*"                              # lat (DDMM.MMMM)
    r"([NS]?)\s*"                                     # N/S
    r"(\d{5}\.\d+|)\s*"                               # lon (DDDMM.MMMM)
    r"([EW]?)\s*"                                     # E/W
    r"(\d*\.?\d*|)\s*"                                # date (ddmmyy)
    r"(\d*\.?\d*|)\s*"                                # time (hhmmss.ss)
    r"(\d*\.?\d*|)\s*"                                # altitude
    r"([\d.]*)\s*"                                    # speed (knots)
    r"([\d.]*)\s*"                                    # course
)
```

También parsea raw NMEA del puerto dedicado (GPGGA, GPGSV) en `src/libs/gps_parser.py`.

## Patrón Service Thread

`src/core/gps_service.py`:

```python
class GPSService(threading.Thread):
    def __init__(self, state: SystemState):
        super().__init__(daemon=True)
        self._state = state
        self._gps: SIM7600GPS | None = None

    def run(self):
        if not os.path.exists(GPS_AT_PORT):
            self._run_stub()  # modo simulación para testing
            return
        self._connect_and_read()

    def _connect_and_read(self):
        self._gps = SIM7600GPS(GPS_AT_PORT, GPS_BAUD)
        self._gps.set_callback(self._on_gps_data)
        self._gps.start()
        self._gps.wait()  # bloquea hasta stop()

    def _on_gps_data(self, data):
        self._state.update_gps(data)
```

## Modo Stub (Simulación)

Cuando no hay hardware GPS, `_run_stub()` genera una trayectoria circular para testear apps:

```python
def _run_stub(self):
    lat, lon = 28.5, -13.8  # Canarias
    while not self._state.shutdown_event.is_set():
        lat += random.uniform(-0.001, 0.001)
        lon += random.uniform(-0.001, 0.001)
        data = SIM7600GPSData(lat, lon, ..., has_fix=True, num_satellites=8)
        self._state.update_gps(data)
        time.sleep(1)
```

## Debugging

```bash
# Verificar que el módulo responde
echo -e "AT\r\n" > /dev/ttyUSB2
cat /dev/ttyUSB2 &

# Ver puertos seriales
ls -la /dev/ttyUSB*
dmesg | grep ttyUSB

# Ver NMEA crudo (ttyUSB1)
cat /dev/ttyUSB1

# Probar AT+CGPSINFO manual
echo -e "AT+CGPSINFO\r\n" > /dev/ttyUSB2
```

**Problemas comunes**:  
- `device reports readiness to read but returned no data` → módulo no encendido, revisar alimentación
- `AT+CGPS=1` timeout → SIM7600 no responde, revisar conexión USB
- Sin fix después de 5 min → antena GPS no conectada o en interiores
- `/dev/ttyUSB*` no aparece → driver CH340 no instalado

## Key Files

| File | Role |
|------|------|
| `src/drivers/sim7600_gps.py` | Driver de bajo nivel (AT commands, NMEA parsing) |
| `src/core/gps_service.py` | Service thread wrapper |
| `src/libs/gps_parser.py` | Parser NMEA alternativo (raw desde ttyUSB1) |
| `src/apps/gps_display_app.py` | App GPS + mapa dual-screen |
| `src/apps/gps_diag_app.py` | App de diagnóstico GPS |
| `src/config_loader.py` | Config: `GPS_AT_PORT`, `GPS_BAUD`, `MAP_ZOOM` |
