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
