# Memoria del Proyecto - MotoMami Ultimate

_Actualizado: 2026-07-27_

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

- **Servicio**: `MqttListenerService` (en `src/services/mqtt_listener.py`) — se suscribe a `motomami/#` y `motomami-input/#` en Mosquitto local, actualiza `Esp32VelocimetroState`, `Esp32DireccionalesState` y `Esp32InputState` en `SystemState`
- **⚠️ Importante**: `motomami/#` NO matchea `motomami-input/...#` (MQTT wildcards no cruzan `-` en top-level topic). Requiere segunda suscripción explícita `motomami-input/#`.
- **App**: `MqttMonitorApp` (en `src/apps/mqtt_monitor_app.py`) — canvas 640x240 (fb2 izq + fb1 der)
  - **Izquierda (fb2)**: Velocímetro 320x240 — velocidad grande, barra gráfica, distancia, odómetro, pulsos
  - **Derecha arriba (fb1)**: Direccionales 320x160 — flechas izq/der, emergencia, frenado, luz nocturna, intensidades (compacto), IP/RSSI/ID en 1 línea
  - **Derecha abajo (fb1)**: Input 320x80 — status dot + IP/RSSI/ID + 5 botones con indicadores: ◄ LEFT, ► RIGHT, ▲ EMERG, ■ BRAKE, ☽ NIGHT (con colores ON/OFF)
- **Refresco**: 300ms (para seguir las publicaciones del ESP32 cada 300ms)
- **Menu key**: `"mqtt"` en `main_menu.py`, launcher en `main.py`
- **Config**: `MQTT_LOCAL_HOST = 192.168.42.1`, `MQTT_LOCAL_PORT = 1883` (configurable en `config_loader.py`)

### Topics monitoreados

| Topic | De | Payload |
|-------|----|---------|
| `motomami/velocimetro/data` | ESP32 velo | `{"s":speed,"d":dist,"p":pulses,"id":dev_id}` cada 300ms |
| `motomami/velocimetro/odometro` | ESP32 velo | `"1.234"` (float string, al conectar) |
| `motomami/velocimetro/status` | ESP32 velo | `"online"/"offline"` (last will) |
| `motomami/velocimetro/ip` `rssi` `id` | ESP32 velo | metadata (retain) |
| `motomami/status` | ESP32 dir | `"online"/"offline"` (last will) |
| `motomami/status/ip` `rssi` `id` | ESP32 dir | IP / RSSI / device id (retain) |
| `motomami-input/status` | ESP32 input | `"online"/"offline"` (last will) |
| `motomami-input/status/ip` `rssi` `id` | ESP32 input | metadata (retain) |
| `motomami-input/data` | ESP32 input | `<msg_id>:<5chars>` donde cada char es GPIO level del pin (0=presionado/pull-down, 1=liberado/pull-up). Parse: `left=[0]`, `right=[1]`, `emerg=[2]`, `brake=[3]`, `night=[4]`. Frecuencia: ~300ms. |

**Nota**: el módulo input publica comandos con prefijo `<msg_id>:` (ej. `42:ON`) — `_strip_msg_id()` lo remueve antes de parsear.

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

## Sesión 2026-07-26 — Xbox BT fix + Tema día/noche + Crispy Doom

### 1. Fix mando Xbox Bluetooth (bug encontrado)

**Causa raíz**: `src/libs/vp_controller.py` no existía (se borró con la limpieza de `final/`). El `InputManager` hacía `from vp_controller import XboxController` → ImportError silencioso → `self._xbox_cls = None` → Xbox NUNCA se inicializaba. "Emparejado" en la app Conexiones es solo a nivel BlueZ; eso no crea `/dev/input/js0`.

**Fix aplicado**:
- `src/libs/vp_controller.py` restaurado desde git history (`final/src/libs/vp_controller.py`), con `CONTROLLER_DEADZONE = 0.3` inline (sin dependencia de `vp_config`)
- `src/core/input_manager.py`: **hot-plug** — si `_xbox is None` o `connected == False`, reintenta `_init_xbox()` cada `XBOX_RETRY_INTERVAL = 3.0s`. Detecta desconexión en runtime (el read_loop de XboxController pone `connected=False` al morir) y reconecta solo.
- Testeado con mocks: reintento tras fallo, detección de desconexión y reconexión OK

**PENDIENTE EN RPI (cuando vuelva SSH)** — para que `/dev/input/js0` aparezca con Xbox One/Series por BT:
```bash
# Verificar primero: conectar mando y ver si existe
ls /dev/input/js*
# Si NO aparece → desactivar ERTM (problema conocido Xbox BT en Linux):
echo 'options bluetooth disable_ertm=1' | sudo tee /etc/modprobe.d/bluetooth.conf
sudo reboot
# Alternativa más robusta: instalar xpadneo (driver DKMS para Xbox BT)
# Verificar eventos: sudo evtest
```

### 2. Tema día/noche

- **`src/libs/theme.py`** (nuevo): dataclass `Theme` (BG/TEXT/ACCENT/semánticos), paletas `NIGHT` (default) y `DAY` (fondo claro 232,234,238, texto oscuro), acentos por app `_APP_ACCENTS`, `get_theme(app)`, `get_mode()`, `set_mode()`, `toggle_mode()`, helper `accent(color)` que oscurece ×0.55 en modo día para legibilidad. **Persiste en `config.ini` `[ui] theme`** (escribe con configparser sin borrar otras claves).
- **Toggle**: entrada `"Tema"` en `main_menu.py` APPS (key `theme`) — ENTER cambia modo al instante sin salir del menú. Muestra "Tema: Día/Noche" dinámico.
- **Apps migradas**: `main_menu.py` (completa) y `mqtt_monitor_app.py` (clase `_Palette` derivada del tema por render).
- **PENDIENTE**: migrar resto de apps al tema (gps_display, bluetooth_manager, connections, music, video, gps_diag, doom) — mismo patrón: `get_theme(app)` + `accent()`.

### 3. Crispy Doom (mouselook)

- Chocolate Doom NO puede mirar arriba/abajo (fiel al Doom original, el motor no renderiza pitch vertical).
- `doom_app.py` `_find_doom_binary()`: ahora prefiere **`crispy-doom`** (fork de Chocolate con mouselook, mismo peso), fallback chocolate-doom.
- **PENDIENTE EN RPI**: `sudo apt install crispy-doom` + activar mouselook (`crispy-doom -setup` → Mouse → Enable mouse look, o `~/.local/share/crispy-doom/crispy-doom.cfg` → `mouse_look 1`).

### Decisiones tomadas

- **Quake**: pospuesto. Quake 1 viable en Zero 2W solo con motor software (tyrquake/SDLQuake); QuakeSpasm/GL muy pesado. Se haría un `quake_app.py` estilo `doom_app.py` (Xvfb+mss).
- **Pantalla HDMI**: el usuario la compró (llega en unos días). Migración fb1/fb2→fb0 pendiente. Ventajas: 60fps GPU, juegos nativos sin hack Xvfb+mss, RetroArch posible. Riesgo: legibilidad solar (necesita panel high-brightness) y consumo.
- **Modo día es solo paleta** — el ST7789 no tiene control de brillo en este setup.

---

## Sesión 2026-07-27 — Deploy RPi + Bug MQTT input no refresca (causa raíz)

### Logros

1. **RPi online** ✅ - SSH a 192.168.31.195 funcional, los 3 ESP32 conectados al AP Motomami-net
2. **ERTM desactivado** ✅ - `disable_ertm=1` aplicado y verificado tras reboot
3. **Xbox emparejado** ✅ - MAC `F4:6A:D7:3F:FE:CD`, necesita encender mando en modo pairing para conectar
4. **MQTT datos vivos verificados** ✅ - velo 300ms OK, direccionales status/ip/rssi/id OK
5. **Input ESP32 SÍ publica** ✅ - `motomami-input/status`, `motomami-input/data`, `ip`, `rssi`, `id` — todos existen y fluyen cada 300ms

### Bug encontrado: MQTT wildcard no matchea input

**Causa raíz**: El listener suscribía solo `motomami/#`. En MQTT, `motomami/#` NO matchea `motomami-input/status` porque `motomami-` ≠ `motomami/` como primer nivel del topic. El wildcard `#` solo expande dentro del mismo árbol de jerarquías.

**Confirmación empírica**: `mosquitto_sub -t 'motomami/#' -v` NO muestra topics `motomami-input/...`, pero `mosquitto_sub -t 'motomami-input/#' -v` SÍ muestra `status`, `data`, `ip`, `rssi`, `id`.

**Fix aplicado en `mqtt_listener.py`**:
- `_connect_and_listen()`: segunda suscripción `client.subscribe("motomami-input/#", qos=1)`
- `_on_connect()`: misma segunda suscripción para reconexión

### Bug menor: lógica invertida en `_handle_input_data`

**Causa**: GPIO pull-up: HIGH=1 (liberado), LOW=0 (presionado). El código trataba `payload[X] == "1"` como True, pero `"1"` significa NO presionado.

**Fix**: `payload[X] == "0"` ahora significa presionado/activo.

### Mejora: `_render_input` ahora muestra estados de los 5 botones

El panel input (320x80, abajo derecha) ahora muestra:
- Header "INPUT" + status dot
- IP/RSSI/ID en línea compacta
- Row 1: ◄ L:ON/OFF (amarillo), ► R:ON/OFF (amarillo), ▲ EM:ON/OFF (rojo)
- Row 2: ■ BR:ON/OFF (rojo), ◉ NT:ON/OFF (azul), timestamp

### Bug: fb_daemon legacy al 99% CPU pisando framebuffer

**Causa**: El service legacy `motomami-fb.service` ejecutaba `final/src/fb_daemon.py` (heredero del sistema `final/`). Estaba **enabled** y se iniciaba en boot, consumiendo 99% CPU y escribiendo al framebuffer constantemente, pisando todo lo que escribiera el nuevo sistema unificado.

**Fix**: `systemctl stop motomami-fb.service && systemctl disable motomami-fb.service`

**Lección**: Al migrar de `final/` a `src/`, verificar que ningún service legacy esté habilitado. El nuevo sistema escribe directo a `/dev/fb*` via mmap, no necesita daemon externo.

### Deploy a RPi

- **Repo correcto**: `MarioAntizana1/Motomami-unificado` en GitHub (NO `wenup/Rpi-motomami-ultimate`)
- **Ruta en RPi**: `/home/motomami/moto/` (NO `/home/motomami/motomami-ultimate/`)
- `curl` desde `raw.githubusercontent.com/MarioAntizana1/Motomami-unificado/<COMMIT>/<PATH>`
- Service restart OK, logs sin errores

## Pendientes / Observaciones

- [X] ~~RPi offline~~ ✅ Conectado, ERTM desactivado, servicio corriendo
- [ ] **Xbox conectar** — encender mando en modo pairing (botón pair) para que `/dev/input/js0` aparezca vía BlueZ + ERTM off
- [ ] **crispy-doom en RPI** — `sudo apt install crispy-doom` + activar mouselook
- [ ] Migrar apps restantes al tema día/noche (gps_display, bluetooth, connections, music, video, doom, gps_diag)
- [ ] Pantalla HDMI (llega en unos días) — plan de migración fb1/fb2→fb0
- [ ] Quake launcher (pospuesto hasta tener HDMI o a petición)
- [ ] Revisar si `config.ini.example` necesita sincronizarse con `config.ini`
- [ ] Verificar que el fix del callback solucionó el problema de coordenadas estáticas en ThingsBoard
- [ ] RPi no tiene git — considerar clonar el repo con `git clone` para facilitar deploys futuros
