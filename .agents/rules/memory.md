# Memoria del Proyecto - MotoMami Ultimate

_Actualizado: 2026-07-18_

---

## Stack confirmado

- **Display**: ST7789 240x320, `/dev/fb1` (abajo) + `/dev/fb2` (arriba), canvas 640x240
- **GPS**: SIM7600-G, AT commands via `/dev/ttyUSB2` (AT) + `/dev/ttyUSB1` (NMEA)
- **MQTT/Cloud**: ThingsBoard (`mqtt.thingsboard.cloud:1883`), token del device en `config.ini`
- **Audio**: pygame.mixer / ALSA / Fiio DAC
- **Input**: GPIO 13/26/5/6/12/16 + mando Xbox Bluetooth
- **RPi**: Zero 2W, user `motomami@192.168.31.195`
- **Proyecto en RPi**: `~/moto/` (NO `~/Rpi-motomami-ultimate/` ni `~/final/`)
- **Repo**: `MarioAntizana1/Motomami-unificado` en GitHub

---

## Arquitectura

### Flujo de datos GPS → ThingsBoard

```
SIM7600 (_request_gps_info @1Hz + _read_nmea @5-10Hz)
  → self.data (SIM7600GPSData, en driver thread)
  → callback cada ~0.4s (+ inmediato tras CGPSINFO)
  → GPSService._on_gps_data()
  → SystemState.update_gps()
  → GPSState.update_from_driver() (convierte NMEA→decimal)
  → gps_display_app render cada ~1s (GPS_REFRESH)
  → TelemetriaService.publish() cada 5s
  → MQTT "v1/devices/me/telemetry"
```

### Bugs corregidos (2026-07-18)

1. **Callback duplicado**: `_request_gps_info()` tenía 3 callbacks. Se eliminaron todos y se puso un callback único en `_read_loop()` cada ~1s con datos combinados de CGPSINFO + NMEA.
   - Archivos: `src/drivers/sim7600_gps.py`
   
2. **NMEA no actualizaba estado**: `_read_nmea()` modificaba `self.data` pero NO disparaba callback. Si CGPSINFO fallaba, el `SystemState` nunca se enteraba de que NMEA tenía fix.
   - Fix: callback único en `_read_loop()` después de ambas lecturas

3. **`gps_cached` incoherente**: En `telemetria_service.py`, `gps_cached` se basaba solo en `has_fix`, no en lo que realmente retornaba `get_display_coords()`.
   - Fix: `gps_cached: 0 if (has_fix and lat != 0.0) else (1 if cached_has_fix else 0)`

4. **NMEA parsers sin timestamp**: `_parse_nmea_gga()` y `_parse_nmea_rmc()` no actualizaban `received_at`.
   - Fix: agregado `self.data.received_at = time.time()` en ambos

5. **StaticMap constructor mal invocado**: Se pasaba `self.zoom` (int) como 3er argumento posicional, pero `staticmap.__init__` espera `(width, height, padding_x, padding_y, url_template, tile_size)`. El int 16 se interpretaba como `padding_x`, rompiendo el render.
   - Fix: `m = StaticMap(self.width, self.height)` sin args extra

6. **render_map usaba staticmap como ruta principal**: staticmap auto-calcula el zoom y no soporta control manual. La app necesita zoom UP/DOWN. Se invirtió el orden: tiles (zoom controlable) → staticmap (fallback).
   - Fix: `render_map` ahora prueba tiles primero, solo cae a staticmap si fallan

7. **Callback GPS lento (~1s)**: El callback en `_read_loop()` disparaba cada 1s, y no había callback inmediato tras CGPSINFO. NMEA (5-10Hz) no se aprovechaba.
   - Fix: callback cada ~0.4s + callback inmediato tras `_request_gps_info()` exitoso

8. **gps_refresh_interval=2s**: Display se actualizaba cada 2s. Reducido a 1s en config.ini. Con callback a 0.4s, el display recibe datos frescos con latencia reducida.

---

## Payload enviado a ThingsBoard

```json
{
  "cpu": 45.2, "ram": 62.3, "ram_used_mb": 1024.0, "disk": 55.0,
  "uptime": 86400.0, "cpu_temp": 52.3, "ip": "192.168.1.100",
  "latitude": -0.2295, "longitude": -78.5249,
  "altitude": 2800.0, "speed_kmh": 60.0, "track_angle": 180.0,
  "satellites": 8, "gps_fix": 1, "gps_cached": 0
}
```

---

## Decisiones importantes

- Usar `src/` (unificado), NO `final/` (legacy)
- `config.ini` en `.gitignore` — contiene tokens
- `.agents/rules/laconexion.md` en `.gitignore` — contiene credenciales SSH
- Todos los servicios son `daemon=True` threads
- El estado global es `SystemState` singleton con locks
- Preferir `ssh-rpi_exec` para comandos en RPi (no SCP/SSH directo desde PowerShell)

## Red WiFi AP (Motomami-net)

- **Adaptador USB**: RTL8192EU (Realtek), driver `rtl8xxxu`
- **IP AP**: `192.168.42.1/24` en `wlan1`
- **SSID**: `Motomami-net`, WPA2, ch 6 (2.4GHz)
- **DHCP**: dnsmasq rango `192.168.42.2-192.168.42.50`
- **Internet**: NAT via iptables, salida por `wlan0` (Mario-wifi)
- **Mosquitto MQTT**: `192.168.42.1:1883` (accesible por ESP32 y celu desde el AP)
- **Futuro internet**: SIM7600 (datos celulares), reemplazará `wlan0` como salida NAT

### Servicios configurados

| Servicio | Rol | Enable |
|---|---|---|
| `hostapd` | AP WiFi (SSID Motomami-net) | ✅ |
| `dnsmasq` | DHCP + DNS para AP | ✅ |
| `netfilter-persistent` | Persistir reglas iptables | ✅ |
| `wlan1-ip.service` | Asignar IP estática a wlan1 | ✅ |
| `mosquitto` | MQTT broker local | ✅ |

### Archivos de config

- `/etc/hostapd/hostapd.conf` — configuración AP
- `/etc/dnsmasq.d/motomami.conf` — DHCP rango AP
- `/etc/systemd/system/wlan1-ip.service` — IP estática wlan1
- `/etc/NetworkManager/conf.d/10-unmanaged-wlan1.conf` — NM ignora wlan1
- `/etc/sysctl.d/99-ipforward.conf` — IP forwarding

## MQTT Monitor App

- **Servicio**: `MqttListenerService` (en `src/services/mqtt_listener.py`) — se suscribe a `motomami/#` en Mosquitto local, actualiza `Esp32VelocimetroState` y `Esp32DireccionalesState` en `SystemState`
- **App**: `MqttMonitorApp` (en `src/apps/mqtt_monitor_app.py`) — canvas 640x240 (fb2 izq + fb1 der)
  - **Izquierda (fb2)**: Velocímetro — velocidad grande, barra gráfica, distancia, odómetro, pulsos
  - **Derecha (fb1)**: Direccionales — flechas izq/der, emergencia, frenado, luz nocturna + intensidad, intensidad general
- **Refresco**: 300ms (para seguir las publicaciones del ESP32 cada 300ms)
- **Menu key**: `"mqtt"` en `main_menu.py`, launcher en `main.py`
- **Config**: `MQTT_LOCAL_HOST = 192.168.42.1`, `MQTT_LOCAL_PORT = 1883` (configurable en `config_loader.py`)

### Topics monitoreados

| Topic | De | Payload |
|-------|----|---------|
| `motomami/velocimetro/data` | ESP32 velo | `{"s":speed,"d":dist,"p":pulses}` cada 300ms |
| `motomami/velocimetro/odometro` | ESP32 velo | `"1.234"` (float string, al conectar) |
| `motomami/velocimetro/status` | ESP32 velo | `"online"/"offline"` (last will) |
| `motomami/status` | ESP32 dir | `"online"/"offline"` (last will) |
| `motomami/status/ip` | ESP32 dir | IP string (al conectar) |
| `motomami/status/rssi` | ESP32 dir | RSSI string (cada ~20s) |

### Topics de control (recibidos por ESP32, monitoreados para estado)

| Topic | Comando |
|-------|---------|
| `motomami/intermitente_izquierda` | ON/OFF |
| `motomami/intermitente_derecha` | ON/OFF |
| `motomami/intermitente_emergencia` | ON/OFF |
| `motomami/frenado` | ON/OFF |
| `motomami/luz_nocturna` | ON/OFF |
| `motomami/luz_nocturna/intensidad` | 0-100 |
| `motomami/intensidad` | 0-100 |

## Graphify (Knowledge Graph)

- **Instalado**: CLI `graphify v0.9.17` + plugin `.opencode/plugins/graphify.js`
- **Grafo construido**: `graphify-out/graph.json` (2215 nodos, 2898 aristas, 188 comunidades)
- **Reporte**: `graphify-out/GRAPH_REPORT.md`
- **Uso**: Consultar con `graphify query "pregunta"` en vez de grepear archivos

---

## Pendientes / Observaciones

- [ ] Revisar si `config.ini.example` necesita sincronizarse con `config.ini`
- [ ] Verificar que el fix del callback solucionó el problema de coordenadas estáticas en ThingsBoard
- [ ] RPi no tiene git — considerar clonar el repo con `git clone` para facilitar deploys futuros
