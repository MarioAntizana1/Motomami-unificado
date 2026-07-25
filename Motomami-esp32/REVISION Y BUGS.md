# Revisión de código y bugs — Motomami ESP32

**Fecha:** 2026-07-24
**Alcance:** Los 3 proyectos ESP32-C6 (direccionales, input, velocímetro) + configs (sdkconfig, platformio.ini, CMakeLists) + comparación contra specs (.md de animaciones) y contra "Instrucciones y funciones.md".
**Nota:** Revisión estática de código, sin flashear nada.

**Leyenda de severidad:**
- 🔴 Crítico — comportamiento roto o pérdida/corrupción de datos
- 🟠 Medio — falla en escenarios reales comunes, degradación funcional
- 🟡 Menor — ineficiencia, spam, fragilidad, código muerto

---

## 1. Bugs críticos 🔴

### 1.1 [Velocímetro] Cálculo de velocidad erróneo → lecturas erráticas

**Archivo:** `Motomami-velocimetro-temperatura-esp32c6/src/main.c` líneas 112–126 (`publish_data`) y 230–234.

La velocidad se calcula como `SPEED_FACTOR / elapsed`, donde `elapsed = ahora - last_pulse_tick`. El problema: `last_pulse_tick` se actualiza en el **loop principal** (cada 10 ms) cuando se consume `pulse_ready`, NO en el ISR. Es decir, mide "tiempo desde que el loop vio el último pulso", no el **período entre pulsos**.

Consecuencias numéricas reales:
- Justo después de un pulso: `elapsed ≈ 10 ms` → velocidad ≈ **162 km/h fantasma**.
- A 90 km/h reales (pulso cada ~18 ms), al publicar cada 300 ms el `elapsed` cae aleatoriamente en [0, 28] ms → velocidad publicada oscila entre **58 y 1620 km/h**.
- A baja velocidad (pulso cada 1 s): la lectura salta entre ~1.6 y 162 km/h.

**Fix sugerido:** guardar en el ISR el tick de cada pulso contado (`last_pulse_tick_isr = now` dentro del ISR al hacer `pulse_count++`) y calcular el período entre dos pulsos consecutivos: `periodo = tick_actual - tick_anterior`; `speed = SPEED_FACTOR / periodo_ms`.

### 1.2 [Velocímetro] Debounce deshabilitado silenciosamente (tick de 10 ms)

**Archivo:** `Motomami-velocimetro-temperatura-esp32c6/src/main.c` líneas 23 y 62–65.

`CONFIG_FREERTOS_HZ=100` → 1 tick = 10 ms. `DEBOUNCE_MS = 2` → `pdMS_TO_TICKS(2) = (2*100)/1000 = 0` ticks (truncado). La condición del ISR queda `(now - last_edge_tick) < 0` → **nunca se cumple** → el debounce está completamente desactivado.

La máquina de estados RISING/FALLING no protege contra rebotes: un rebote sube-baja-sube-baja cuenta **2 pulsos** en vez de 1. Con un sensor tipo reed magnético (que rebota mucho) esto infla el odómetro.

**Fix sugerido:** subir `CONFIG_FREERTOS_HZ` a 1000, o cambiar la comparación a milisegundos con `esp_timer_get_time()` (IRAM-safe), o poner `DEBOUNCE_MS >= 10`.

### 1.3 [Direccionales] Doble inicialización del cliente MQTT al reconectar WiFi

**Archivo:** `Motomami-direccionales-esp32c6/main/main.c` líneas 422–435 (`wifi_event_handler`) y 404–417 (`start_mqtt`).

`IP_EVENT_STA_GOT_IP` se dispara en **cada** reconexión WiFi, no solo en la primera. Cada vez llama `start_mqtt()`, que hace `esp_mqtt_client_init()` + `esp_mqtt_client_start()` de nuevo. El handle global `mqtt_client` se sobrescribe: el cliente anterior queda **vivo pero perdido** (fuga de memoria), y como la librería auto-reconecta, ambos clientes terminan conectados → **suscripciones y publicaciones duplicadas**, y cada reconexión WiFi agrega otro cliente más.

**Fix sugerido:** en `start_mqtt()`, proteger con `if (mqtt_client != NULL) return;` o destruir el cliente previo con `esp_mqtt_client_destroy()` antes de reinicializar.

---

## 2. Bugs medios 🟠

### 2.1 [Input] Arranque bloqueante: controles muertos hasta que el broker responda

**Archivo:** `Motomami-input-esp32c6/src/main.c` líneas 210, 239 y 242.

`app_main` hace `xEventGroupWaitBits(..., portMAX_DELAY)` primero por WiFi y luego por MQTT, y **recién después** crea `input_task`. Como la RPi tarda en arrancar (y es quien corre el broker), los botones/intermitentes/freno **no hacen nada** durante toda esa ventana. Si el broker nunca aparece, queda bloqueado para siempre.

Esto contradice directamente "Instrucciones y funciones.md" (reconexión instantánea + acumular en memoria mientras no hay conexión).

**Fix sugerido:** crear `input_task` antes de las esperas y encolar los cambios de estado para publicarlos cuando MQTT conecte.

### 2.2 [Input] Cambios de estado se pierden si MQTT está caído (no hay buffer)

**Archivo:** `Motomami-input-esp32c6/src/main.c` líneas 133–138.

Cuando un pin cambia y MQTT no está conectado, solo se loguea `MQTT NO disponible` y el evento **se descarta**. El requerimiento pide acumular mensajes con ID y liberarlos al reconectar. Hoy, si el broker cae con un intermitente encendido, el módulo de direccionales nunca se entera del cambio.

### 2.3 [Velocímetro] Pulsos perdidos durante escrituras NVS/flash

**Archivo:** `Motomami-velocimetro-temperatura-esp32c6/src/main.c` línea 187; `sdkconfig.seeed_xiao_esp32c6` línea 1291.

`gpio_install_isr_service(0)` sin `ESP_INTR_FLAG_IRAM` y `# CONFIG_GPIO_CTRL_FUNC_IN_IRAM is not set`. Durante un borrado/escritura de flash (cada `save_nvs`, ~cada 112 m recorridos) las interrupciones GPIO quedan enmascaradas → **pulsos que llegan en esa ventana se pierden** → el odómetro subestima levemente. No crashea (esa parte está bien), pero a 90 km/h se pueden perder 1–2 pulsos por guardado.

**Fix sugerido:** `gpio_install_isr_service(ESP_INTR_FLAG_IRAM)` + `CONFIG_GPIO_CTRL_FUNC_IN_IRAM=y` (el ISR ya es `IRAM_ATTR`).

### 2.4 [Velocímetro] Velocidad fantasma durante los primeros 3 s tras arrancar

**Archivo:** `Motomami-velocimetro-temperatura-esp32c6/src/main.c` líneas 56, 117–121.

`last_pulse_tick = 0` al boot → `elapsed = uptime` < 3000 ms durante 3 s → publica una velocidad que decae de ~162 km/h a 0 aunque la rueda jamás giró. Se arregla junto con el bug 1.1 (inicializar en "sin pulso" = velocidad 0).

---

## 3. Bugs menores / observaciones 🟡

| # | Proyecto | Hallazgo |
|---|----------|----------|
| 3.1 | Velocímetro | Cuando la moto se detiene, guarda NVS y loguea "DETENIDO - odometro guardado" **cada 3 s para siempre** (líneas 242–248). NVS omite la escritura si el valor no cambia (no hay desgaste de flash), pero el log spam es infinito. |
| 3.2 | Direccionales | Variable `wifi_connected` se escribe (líneas 427, 431) pero **nunca se lee** → código muerto. |
| 3.3 | Todos | Reconexión WiFi inmediata dentro del event handler sin backoff. Funciona, pero con el AP caído genera intentos en ráfaga. Considerar pequeño delay/backoff. |
| 3.4 | Todos | Reconexión MQTT depende del auto-reconnect de esp_mqtt (default ~10 s). Para "reconexión instantánea" conviene bajar `network.reconnect_timeout_ms`. |
| 3.5 | Velocímetro | Publica datos con **QoS 2 cada 300 ms** (líneas 106–109, 27). El handshake de QoS 2 ×3.3 msg/s es tráfico innecesario; QoS 0/1 sobra para telemetría continua. |
| 3.6 | Input | QoS 2 para todo, incluidos RSSI y status (línea 59). Mismo comentario. |
| 3.7 | Direccionales | Buffer de payload MQTT de 16 bytes (línea 362). OK para "ON"/"OFF"/"100", frágil si crece el protocolo. |
| 3.8 | Velocímetro | El ISR inicializa `pulse_state = WAITING_RISING`; si el pin arranca en HIGH, el primer flanco de bajada se ignora. Sin impacto real (se autoconfigura en el siguiente imán), pero documentado. |

---

## 4. Gaps contra "Instrucciones y funciones.md"

| Requisito | Direccionales | Input | Velocímetro |
|-----------|:---:|:---:|:---:|
| OTA (HTTP server POST /ota) | ❌ | ❌ | ❌ |
| ID contador de mensajes | ❌ | ❌ | ❌ |
| Estado (online/offline + LWT) | ✅ | ✅ | ✅ |
| RSSI periódico | ✅ (~21 s) | ✅ (21 s) | ❌ **no publica** |
| IP publicada | ✅ | ✅ | ❌ **solo log** |
| Buffer cuando MQTT cae | N/A (receptor) | ❌ descarta | ✅ acumula pulsos (excepción permitida) |
| Reconexión instantánea | ⚠️ bug 1.3 | ⚠️ bloqueante (bug 2.1) | ⚠️ bloqueante pero ISR ya cuenta pulsos |

**Adicional — esquemas de topics inconsistentes entre proyectos:**
- Direccionales: `motomami/status`, `motomami/status/ip`, `motomami/status/rssi`
- Input: `motomami-input/status`, `motomami-input/status/ip`, `motomami-input/status/rssi`
- Velocímetro: `motomami/velocimetro/status`, `.../data`, `.../odometro`

Tres jerarquías distintas; conviene unificar (p. ej. `motomami/<modulo>/status|ip|rssi|id`) para el parser de la RPi.

---

## 5. Problemas de configuración (bloquean el OTA futuro)

| Proyecto | Flash configurada | Partición | Problema |
|----------|-------------------|-----------|----------|
| direccionales | **2 MB** (sdkconfig línea 1014) | `SINGLE_APP_LARGE` | El XIAO ESP32-C6 tiene 4 MB; se desperdician 2 MB y **no hay partición OTA** |
| input | **2 MB** en sdkconfig, pero `sdkconfig.defaults` pide **4 MB** | `SINGLE_APP` | Conflicto: `sdkconfig.defaults` solo aplica al regenerar sdkconfig; hoy manda el 2 MB. Sin partición OTA |
| velocímetro | 4 MB ✅ | `SINGLE_APP` | Sin partición OTA |

Para OTA los 3 necesitan pasar a tabla `TWO_OTA` (y direccionales corregir el tamaño de flash a 4 MB). Ninguno tiene `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE` (opcional pero recomendable para OTA seguro con auto-rollback).

---

## 6. Deriva documentación ↔ código (direccionales)

- **Color intermitente:** `INTERMITENTE IZQ.md`/`DERECHO.md` dicen `245, 233, 66` (amarillo) pero el código usa `255, 200, 0` (ámbar, main.c líneas 34–36). El ámbar es el correcto para direccionales de moto → actualizar los .md.
- **Luz nocturna:** `Luz de noche.md` pide "arcoíris"; el código oscila hue 140–210 (azul-verde-violeta, líneas 61–63). Decidir cuál vale y alinear.
- ✅ Verificado frame a frame: las animaciones de intermitentes (14 frames: shrink 3 filas → grow fila central), frenado full-matrix, frenado+intermitente (solo columnas 9–18) y noche (filas 0/2/4, freno anula noche) **coinciden con los .md de spec**.

---

## 7. Seguridad (notas, no bugs)

- SSID/password y IP del broker hardcodeados en los 3 `main.c`. Aceptable en red privada, pero documentado.
- El futuro endpoint `POST /ota` quedará abierto a cualquiera en la red WiFi → agregar al menos un token/header de validación cuando se implemente.

---

## 8. Verificado OK (sin bugs encontrados)

- Mapeo zig-zag `index_of` consistente con "LED 0 = esquina superior derecha" y con los frames de los specs.
- Prioridades de render: freno > noche > intermitentes; freno+intermitente pinta solo el centro ✅ igual que el spec.
- LWT retained `offline` + publicación `online` retained en los 3 ✅.
- Input publica estados ON/OFF **retained** → direccionales sincroniza su estado al suscribirse ✅.
- Velocímetro instala el ISR **antes** de las esperas WiFi/MQTT → no se pierden pulsos durante el arranque ✅.
- Debounce de input (50 ms / 5 ticks) correcto con tick de 10 ms ✅.
- Pines usados válidos en XIAO ESP32-C6 (D2/D3/D4/D5/D10, GPIO21) ✅.
- Overflow de `xTaskGetTickCount()` manejado correctamente por aritmética unsigned en debounces ✅.
- NVS del odómetro: carga al boot, guarda cada 250 pulsos y al detenerse; no hay doble conteo tras reinicio ✅.

---

## Resumen

| Severidad | Cantidad |
|-----------|----------|
| 🔴 Críticos | 3 |
| 🟠 Medios | 4 |
| 🟡 Menores | 8 |
| Gaps de requerimientos | 5 (+ topics inconsistentes) |
| Problemas de config que bloquean OTA | 3 proyectos |

**Top 3 a arreglar primero:** 1.3 (doble MQTT en direccionales), 1.1+1.2 (velocidad y debounce del velocímetro), 2.1+2.2 (input bloqueante y sin buffer).

---

## 9. Resolución — 2026-07-24

| Bug | Estado | Fix |
|-----|--------|-----|
| 1.1 Velocidad errónea | ✅ Corregido | ISR guarda periodo entre pulsos con `esp_timer_get_time()`; `current_speed()` usa periodo real + decaimiento suave al detenerse. Sin velocidad fantasma al boot. |
| 1.2 Debounce desactivado | ✅ Corregido | Debounce real de 2 ms con `esp_timer_get_time()` (microsegundos, IRAM-safe). Ya no depende de `xTaskGetTickCount` (10 ms). |
| 1.3 Doble MQTT direccionales | ✅ Corregido | `start_mqtt()` protegido con `if (mqtt_client != NULL) return`. |
| 2.1 Input bloqueante | ✅ Corregido | `input_task` se crea antes de iniciar WiFi/MQTT. Arranque completamente no bloqueante. |
| 2.2 Cambios perdidos sin MQTT | ✅ Corregido | Buffer circular de 32 mensajes con ID. Los cambios se encolan y se liberan al reconectar. |
| 2.3 Pulsos perdidos en NVS | ✅ Corregido | `gpio_install_isr_service(ESP_INTR_FLAG_IRAM)` + `CONFIG_GPIO_CTRL_FUNC_IN_IRAM=y`. El ISR ya era `IRAM_ATTR`. |
| 2.4 Velocidad fantasma 3 s | ✅ Corregido | Arreglado junto con 1.1: `last_pulse_us = 0` al boot → velocidad 0 hasta que lleguen pulsos. |
| 3.1 Spam "DETENIDO" | ✅ Corregido | Flag `stopped_saved`: guarda NVS una sola vez al transicionar a detenido. Sin spam. |
| 3.2 wifi_connected muerto | ✅ Corregido | Variable eliminada (nunca se usaba). |
| 3.3 Reconexión WiFi sin backoff | ✅ Corregido | Backoff de 1 s con `esp_timer` antes de `esp_wifi_connect()`. |
| 3.4 MQTT reconnect_timeout | ✅ Corregido | `network.reconnect_timeout_ms = 1000` en los 3 módulos. |
| 3.5 QoS 2 velocímetro | ✅ Corregido | Datos de telemetría a QoS 0; status/odómetro/IP QoS 1 retained. LWT QoS 1. |
| 3.6 QoS 2 input | ✅ Corregido | Estados QoS 1 retained; RSSI/ID QoS 0. LWT QoS 1. |
| 3.7 Buffer payload 16 bytes | ✅ Corregido | Ampliado a 32 bytes en direccionales. Soporta `<id>:ON`/`OFF`. |
| 3.8 ISR estado inicial | ✅ Corregido | `pulse_state` se inicializa según el nivel real del pin al boot. |

### Gaps implementados

| Gap | Estado |
|-----|--------|
| OTA (HTTP POST /ota) | ✅ Los 3 módulos: servidor HTTP en puerto 80, endpoint POST /ota con header X-OTA-Token, GET / info. Partición `TWO_OTA` (2×~2MB) para flash 4MB. Rollback con auto-validación a 30 s. |
| ID contador de mensajes | ✅ Input: id en payload `<id>:ON`/`OFF`. Velocímetro: `"id":N` en JSON. Direccionales: `motomami/status/id` + id en RSSI periódico. |
| RSSI velocímetro | ✅ Publica `motomami/velocimetro/rssi` cada 21 s (QoS 0 retained). |
| IP velocímetro | ✅ Publica `motomami/velocimetro/ip` en connect (QoS 1 retained). |
| Buffer input | ✅ Ring buffer de 32 entradas; id asignado al encolar. Flush en orden FIFO al reconectar + sync de estado actual. |
| TX power reducido | ✅ `esp_wifi_set_max_tx_power(40)` (10 dBm) en los 3 módulos. El AP del RPi está en la moto (<2 m). |
| Brownout detector | ✅ Nivel bajado de 7 a 2 (~2.43V) para tolerar dips de alimentación USB. |

### Compatibilidad

- Payloads `id:ON`/`OFF`: parseados por direccionales (`strrchr(payload, ':')`) y por `mqtt_listener.py` de la RPi (`_strip_msg_id`).
- Velocímetro JSON con `"id":N`: backward-compatible (el parser usa `.get()`).
- Topics de status no se renombraron (no break la RPi).
