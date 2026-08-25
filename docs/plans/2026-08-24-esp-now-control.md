# ESP-NOW Control de Luz Trasera — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Migrar el control de la luz trasera (direccionales) del tramo MQTT-vía-RPi a ESP-NOW directo desde el módulo input, con watchdog de software y timeout RMT para auto-recuperación en calle.

**Architecture:** El input emite por ESP-NOW broadcast (payload `"<msg_id>:LLLLL"`, canal 6 fijo) ante cada cambio de pin y cada 150 ms. El direccionales recibe, mapea a sus flags internos y su render loop queda intacto. WiFi/MQTT/OTA siguen como best-effort (status para el monitor de la RPi). Ambos firmwares ganan SW WDT (`esp_timer` + `esp_restart()`) y el direccionales un timeout en `rmt_tx_wait_all_done`.

**Tech Stack:** ESP-IDF (PlatformIO para input, IDF v6.0.2 puro para direccionales), ESP-NOW API (`esp_now.h`, parte de `esp_wifi`), RMT, esp_timer, pio/idf.py.

**Design doc:** `docs/plans/esp-now-control-design.md` (entendimiento + Decision Log)

---

## Task 1: Input — Init ESP-NOW + envío por cambio de pin y refresco 150 ms

**Files:**
- Modify: `Motomami-esp32/Motomami-input-esp32c6/src/main.c`

**Step 1: Agregar includes y constantes**

Agregar tras `#include "mqtt_client.h"`:
```c
#include "esp_now.h"
```

Agregar en la sección `WIFI / MQTT`:
```c
#define ESPNOW_CHANNEL    6
#define ESPNOW_REFRESH_MS 150
```

Agregar en la sección `ESTADO GLOBAL`:
```c
static uint8_t espnow_broadcast_mac[ESP_NOW_ETH_ALEN] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
```

**Step 2: Funciones de envío ESP-NOW** (antes de `input_task`)

```c
static uint32_t espnow_next_id(void)
{
    portENTER_CRITICAL(&buf_mux);
    uint32_t id = ++msg_id;
    portEXIT_CRITICAL(&buf_mux);
    return id;
}

static void espnow_send_cb(const uint8_t *mac_addr, esp_now_send_status_t status)
{
    if (status != ESP_NOW_SEND_SUCCESS) {
        ESP_LOGW(TAG, "ESP-NOW envio fallido");
    }
}

static void espnow_send_state(void)
{
    char payload[24];
    snprintf(payload, sizeof(payload), "%lu:%d%d%d%d%d", espnow_next_id(),
        gpio_get_level(in_pins[0]), gpio_get_level(in_pins[1]),
        gpio_get_level(in_pins[2]), gpio_get_level(in_pins[3]),
        gpio_get_level(in_pins[4]));
    esp_now_send(espnow_broadcast_mac, (const uint8_t *)payload, strlen(payload));
}

static void espnow_init(void)
{
    ESP_ERROR_CHECK(esp_wifi_set_channel(ESPNOW_CHANNEL, WIFI_SECOND_CHAN_NONE));
    ESP_ERROR_CHECK(esp_now_init());
    esp_now_register_send_cb(espnow_send_cb);
    esp_now_peer_info_t peer = {0};
    memcpy(peer.peer_addr, espnow_broadcast_mac, ESP_NOW_ETH_ALEN);
    peer.channel = ESPNOW_CHANNEL;
    peer.ifidx = WIFI_IF_STA;
    peer.encrypt = false;
    ESP_ERROR_CHECK(esp_now_add_peer(&peer));
    ESP_LOGI(TAG, "ESP-NOW listo (broadcast, canal %d)", ESPNOW_CHANNEL);
}
```

**Step 3: Llamar `espnow_init()` tras `esp_wifi_start()`**

En `wifi_init()`, después de `esp_wifi_start();`:
```c
    espnow_init();
```

**Step 4: Enviar en `input_task`**

Declarar `TickType_t last_espnow = 0;` junto a `last_data_pub`. Dentro del `while(1)`, tras el bloque de 300 ms de `publish_all_state()`:
```c
        if (now - last_espnow >= pdMS_TO_TICKS(ESPNOW_REFRESH_MS)) {
            last_espnow = now;
            espnow_send_state();
        }
```
Y en el bloque de cambio de estado, tras `publish_all_state();` (dentro de `if (r != in_current_state[i])`):
```c
                    espnow_send_state();
```

**Step 5: Build**

Run: `pio run` (en `Motomami-esp32/Motomami-input-esp32c6`)
Expected: `SUCCESS` sin warnings nuevos.

**Step 6: Flash + verificar en serie**

Run: `pio run --target upload`, luego `pio device monitor`
Expected: log `ESP-NOW listo (broadcast, canal 6)`; al presionar cada botón aparece el envío (send OK silencioso, fallos loguean).

**Step 7: Commit**

```bash
git add Motomami-esp32/Motomami-input-esp32c6/src/main.c
git commit -m "feat(input): enviar estado de pines por ESP-NOW broadcast (canal 6, 150ms)"
```

---

## Task 2: Input — SW WDT

**Files:**
- Modify: `Motomami-esp32/Motomami-input-esp32c6/src/main.c`

**Step 1: Constante + variable global**

En sección `ESTADO GLOBAL`:
```c
#define WDT_TIMEOUT_US (5 * 1000 * 1000)
static volatile int64_t wdt_last_kick_us = 0;
```

**Step 2: Callback del watchdog**

```c
static void wdt_timer_cb(void *arg)
{
    (void)arg;
    if ((esp_timer_get_time() - wdt_last_kick_us) > WDT_TIMEOUT_US) {
        ESP_LOGE(TAG, "WDT: bucle principal colgado, reiniciando");
        esp_restart();
    }
}
```

**Step 3: Crear el timer en `app_main`** (tras `xTaskCreate(input_task, ...)`)

```c
    esp_timer_create_args_t wdt_args = { .callback = wdt_timer_cb, .name = "sw_wdt" };
    esp_timer_handle_t wdt_timer;
    ESP_ERROR_CHECK(esp_timer_create(&wdt_args, &wdt_timer));
    ESP_ERROR_CHECK(esp_timer_start_periodic(wdt_timer, 1000 * 1000));
```

**Step 4: Kick en `input_task`**

Al inicio del `while(1)`:
```c
        wdt_last_kick_us = esp_timer_get_time();
```

**Step 5: Build + flash**

Run: `pio run` → `pio run --target upload`
Expected: `SUCCESS`; el sistema corre normal (sin resets espontáneos).

**Step 6: Commit**

```bash
git add Motomami-esp32/Motomami-input-esp32c6/src/main.c
git commit -m "feat(input): software watchdog con esp_restart si el bucle se cuelga"
```

---

## Task 3: Direccionales — Receptor ESP-NOW + canal 6 + quitar suscripciones MQTT de control

**Files:**
- Modify: `Motomami-esp32/Motomami-direccionales-esp32c6/main/main.c`

**Step 1: Include + constantes**

Tras `#include "mqtt_client.h"`:
```c
#include "esp_now.h"
```

En sección `WIFI / MQTT`:
```c
#define ESPNOW_CHANNEL 6
```

En `ESTADO GLOBAL`:
```c
static volatile uint32_t espnow_last_id = 0;
```

**Step 2: Callback de recepción** (después de `luz_nocturna()`)

```c
static void espnow_recv_cb(const esp_now_recv_info_t *info, const uint8_t *data, int len)
{
    (void)info;
    if (len < 7 || len >= 24) return;              /* "id:LLLLL" */
    char buf[24];
    memcpy(buf, data, len);
    buf[len] = 0;

    char *colon = strchr(buf, ':');
    if (!colon) return;
    *colon = 0;
    uint32_t id = strtoul(buf, NULL, 10);
    int32_t diff = (int32_t)(id - espnow_last_id);
    if (diff <= 0 && diff > -10000) return;        /* duplicado/atrasado; -10000 tolera reboot del emisor */

    const char *s = colon + 1;
    if (strlen(s) < 5) return;

    espnow_last_id = id;
    left_active   = (s[0] == '0');
    right_active  = (s[1] == '0');
    hazard_active = (s[2] == '0');
    brake_active  = (s[3] == '0');
    night_active  = (s[4] == '0');
    ESP_LOGI(TAG, "ESP-NOW %lu:%c%c%c%c%c", id, s[0], s[1], s[2], s[3], s[4]);
}
```

**Step 3: Init ESP-NOW en `wifi_init()`** (después de `esp_wifi_start();`)

```c
    ESP_ERROR_CHECK(esp_wifi_set_channel(ESPNOW_CHANNEL, WIFI_SECOND_CHAN_NONE));
    ESP_ERROR_CHECK(esp_now_init());
    esp_now_register_recv_cb(espnow_recv_cb);
    ESP_LOGI(TAG, "ESP-NOW receptor listo (canal %d)", ESPNOW_CHANNEL);
```

**Step 4: Quitar suscripciones MQTT de control** en `MQTT_EVENT_CONNECTED`

Eliminar las 5 líneas de `esp_mqtt_client_subscribe` para `motomami/intermitente_*`, `motomami/frenado` y `motomami/luz_nocturna`. **Conservar** `motomami/luz_nocturna/intensidad` y `motomami/intensidad`.

**Step 5: Poda del handler `MQTT_EVENT_DATA`**

Eliminar los branches de `intermitente_izquierda/derecha/emergencia`, `frenado` y `luz_nocturna`; conservar únicamente los de `luz_nocturna/intensidad` e `intensidad`.

**Step 6: Build**

Run: `idf.py build` (en `Motomami-esp32/Motomami-direccionales-esp32c6`)
Expected: `SUCCESS`.

**Step 7: Flash + verificar**

Run: `idf.py -p COM3 flash`, luego `idf.py -p COM3 monitor`
Expected: log `ESP-NOW receptor listo (canal 6)`; presionando botones del input (firmware Task 1) aparecen líneas `ESP-NOW <id>:<5 chars>` y la matriz reacciona (intermitentes, frenado, emergencia, nocturna).

**Step 8: Commit**

```bash
git add Motomami-esp32/Motomami-direccionales-esp32c6/main/main.c
git commit -m "feat(direccionales): recibir control por ESP-NOW; MQTT solo status"
```

---

## Task 4: Direccionales — Timeout RMT + SW WDT

**Files:**
- Modify: `Motomami-esp32/Motomami-direccionales-esp32c6/main/main.c`

**Step 1: Constantes + variable**

En `ESTADO GLOBAL`:
```c
#define RMT_TX_TIMEOUT_MS 500
#define WDT_TIMEOUT_US    (5 * 1000 * 1000)
static volatile int64_t wdt_last_kick_us = 0;
```

**Step 2: Callback WDT** (junto al callback ESP-NOW)

```c
static void wdt_timer_cb(void *arg)
{
    (void)arg;
    if ((esp_timer_get_time() - wdt_last_kick_us) > WDT_TIMEOUT_US) {
        ESP_LOGE(TAG, "WDT: render loop colgado, reiniciando");
        esp_restart();
    }
}
```

**Step 3: Timeout en `send_leds()`**

Reemplazar:
```c
    rmt_tx_wait_all_done(led_chan, portMAX_DELAY);
```
por:
```c
    if (rmt_tx_wait_all_done(led_chan, pdMS_TO_TICKS(RMT_TX_TIMEOUT_MS)) != ESP_OK) {
        ESP_LOGE(TAG, "RMT sin respuesta, reiniciando");
        esp_restart();
    }
```

**Step 4: Kick en `render_task`** (al inicio del `while(1)`)

```c
        wdt_last_kick_us = esp_timer_get_time();
```

**Step 5: Crear timer en `app_main`** (tras `xTaskCreate(render_task, ...)`)

```c
    esp_timer_create_args_t wdt_args = { .callback = wdt_timer_cb, .name = "sw_wdt" };
    esp_timer_handle_t wdt_timer;
    ESP_ERROR_CHECK(esp_timer_create(&wdt_args, &wdt_timer));
    ESP_ERROR_CHECK(esp_timer_start_periodic(wdt_timer, 1000 * 1000));
```

**Step 6: Build + flash**

Run: `idf.py build` → `idf.py -p COM3 flash`
Expected: `SUCCESS`; matriz funciona normal, sin resets espontáneos.

**Step 7: Commit**

```bash
git add Motomami-esp32/Motomami-direccionales-esp32c6/main/main.c
git commit -m "feat(direccionales): timeout RMT 500ms y software watchdog con esp_restart"
```

---

## Task 5: Verificación integral en banco (sin RPi)

**Files:** ninguno.

**Prerequisito:** RPi AP **apagado** (o `sudo systemctl stop hostapd dnsmasq mosquitto`).

**Step 1: Arrancar ambos módulos y verificar**

- Input: `pio device monitor` → `ESP-NOW listo (broadcast, canal 6)`
- Direccionales: `idf.py -p COM3 monitor` → `ESP-NOW receptor listo (canal 6)`
- Expected: aunque WiFi no asocie (RPi off), ambos logs aparecen.

**Step 2: Prueba funcional de los 5 botones**

Conectar cada entrada optoacoplada (puente a GND simula pulso LOW):
- LEFT → intermitente izquierdo parpadea
- RIGHT → intermitente derecho parpadea
- EMERG → ambos lados parpadean
- BRAKE → matriz roja
- NIGHT → luz nocturna (hue azul-verde pulsante)
- Expected: respuesta ≤150 ms en cada caso.

**Step 3: Prueba de pérdida de enlace**

Cortar alimentación del input mientras BRAKE activo. Expected: la matriz **mantiene** el último estado (rojo) — decisión documentada.

**Step 4: Prueba de reboot del input**

Reconectar alimentación del input. Expected: en ≤150 ms el direccionales vuelve a reflejar el estado real (la tolerancia `-10000` del msg_id acepta el contador reseteado).

**Step 5: Prueba OTA (con RPi encendida)**

Restaurar RPi (`sudo systemctl start hostapd dnsmasq mosquitto`). Verificar en el monitor de la RPi que input/direccionales publican status/IP/RSSI y que `POST /ota` sigue respondiendo.

---

## Task 6: Deploy + memoria

**Files:**
- Modify: `.agents/rules/memory.md`

**Step 1: Commit final**

```bash
git add .
git commit -m "docs: plan y diseño de control por ESP-NOW (luz trasera)"
git push
```

**Step 2: Actualizar `memory.md`**

Agregar sección de sesión 2026-08-24:
- Control input→direccionales migrado a ESP-NOW broadcast canal 6 (payload `"<msg_id>:LLLLL"`, 150 ms).
- MQTT queda como status/telemetría best-effort para el monitor RPi.
- SW WDT 5 s + timeout RMT 500 ms en ambos firmwares; sin enlace → último estado.
- Velocímetro: pendiente diagnóstico (fuera de alcance).
- Nota: si se cambia el canal del AP Motomami-net, actualizar `ESPNOW_CHANNEL` en ambos firmwares.

**Step 3: Graphify**

Run: `graphify update .` (repo raíz).

---

## Riesgos y verificación

- **ESP-NOW en C6 + IDF**: validar en Task 5 que el refresco 150 ms no se degrada con WiFi conectado; si hubiera pérdida, subir a 200 ms.
- **`esp_wifi_set_channel` en STA**: con el AP en canal 6 no hay conflicto; si algún día el AP cambia de canal, hay que re-sincronizar `ESPNOW_CHANNEL`.
- **Nada de la RPi cambia** (`mqtt_listener.py` intacto): el monitor sigue leyendo `motomami-input/data` y los topics de control que el input sigue publicando.
