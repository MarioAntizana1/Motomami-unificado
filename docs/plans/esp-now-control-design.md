# Diseño: Control de luz trasera por ESP-NOW (MotoMami)

_Fecha: 2026-08-24_
_Estado: Validado, pendiente de implementación_

---

## Entendimiento

- **Qué se construye**: Comunicación directa por ESP-NOW entre el módulo input (emisor, 5 botones optoacoplados) y el módulo direccionales/luz trasera (receptor, matriz NeoPixel 5×28), reemplazando el tramo MQTT para el control de luces.
- **Por qué**: Hoy el control viaja `input → MQTT → Mosquitto (RPi) → MQTT → direccionales`. La RPi es un broker en el medio que no aporta al control (solo escucha). Si la RPi arranca lento o se cae, las luces quedan sin control. El síntoma real observado es "a veces funciona, a veces no" (carrera de reconexión WiFi/MQTT).
- **Para quién**: La luz trasera (frenado, intermitentes, emergencia, luz nocturna) debe responder **siempre**, incluso con la RPi apagada.
- **Restricciones**:
  - Input: ESP-IDF vía PlatformIO, `src/main.c`.
  - Direccionales: ESP-IDF v6.0.2 (puro), `main/main.c`.
  - Ambos ESP32-C6, ambos inician WiFi STA + antena u.FL (GPIO14).
  - La RPi **no publica** comandos de control (solo escucha para el monitor).
  - OTA, WiFi y MQTT deben seguir funcionando (secundarios).
- **No objetivos** (fuera de alcance):
  - Diagnóstico del velocímetro (se trata en otra sesión).
  - Migrar el tramo ESP32→RPi (velocímetro sigue por MQTT).
  - Cambiar OTA ni anti-rollback.
  - Migrar apps de la RPi (mqtt_listener queda igual).

## Supuestos

- ESP-NOW se usa en modo broadcast, canal WiFi **6** fijado explícitamente en ambos STA (coincide con Motomami-net), de modo que funciona aunque el AP de la RPi esté caído.
- El input ya conoce los estados de los 5 pines y seguirá publicándolos a MQTT (best-effort) para que el monitor de la RPi siga viendo input y direccionales.
- La pérdida de un paquete ESP-NOW se tolera con refresco periódico (150 ms) + envío inmediato al cambiar un pin.
- Sin enlace ESP-NOW: se mantiene el último estado recibido (decisión del usuario).
- `msg_id` protege contra paquetes duplicados/atrasados (con tolerancia a reset del emisor).

## Arquitectura

```
[Botones físicos] → input ESP32-C6 ──ESP-NOW (canal 6)──► direccionales ESP32-C6 → Matriz LED
        │                                                  ▲
        └──MQTT (best-effort)──► Mosquitto RPi ←─status/ip/rssi/id──┘
                                  └─► MqttListenerService → MqttMonitorApp (solo lectura)
```

- El camino de control es 100% ESP-NOW y arranca en ms, sin esperar WiFi asociado ni broker.
- WiFi/MQTT/OTA son best-effort: cuando la RPi esté disponible (AP canal 6), los ESP32 se asocian, publican status y habilitan OTA.
- La RPi no requiere cambios de código.

## Protocolo ESP-NOW

- **Payload**: `"<msg_id>:LLLLL"` — 5 chars de estado, mismo orden y convención que `motomami-input/data`:
  - `L` = intermitente izquierdo (pin GPIO18)
  - `R` = intermitente derecho (pin GPIO2)
  - `E` = emergencia (pin GPIO21)
  - `B` = frenado (pin GPIO22)
  - `N` = luz nocturna (pin GPIO23)
  - `'0'` = presionado/activo, `'1'` = liberado (pull-up: LOW=activo). Ejemplo: `"42:01100"`.
- **Frecuencia**: inmediato ante cada cambio de pin + refresco cada **150 ms**.
- **Recepción (direccionales)**: mapeo directo a flags internos `left_active`, `right_active`, `hazard_active`, `brake_active`, `night_active`. El render loop no se toca.
- **Deduplicación**: se acepta si `delta = (int32_t)(id - last_id) > 0` o si `delta < -1000` (el emisor reinició su contador); se ignora el resto.

## Robustez

1. **SW WDT (ambos)**: timer `esp_timer` periódico de 1 s que verifica un `last_kick` actualizado por el bucle principal; si supera 5 s sin kick → `esp_restart()`. Captura bucles infinitos y tareas bloqueadas (el Task WDT de IDF no dispara si la tarea espera semáforo).
2. **Timeout RMT (direccionales)**: `rmt_tx_wait_all_done(chan, pdMS_TO_TICKS(500))` en vez de `portMAX_DELAY`; si expira → log + `esp_restart()`. Es el punto más probable de cuelgue real.
3. **Sin enlace ESP-NOW**: se mantiene el último estado (sin cambios de flags). No se apaga nada ante pérdida de radio.
4. **Ya existentes (sin tocar)**: retry WiFi 1 s, reconnect MQTT 1 s, `ota_boot_init()` anti-rollback 30 s, failsafe natural de pull-ups (cable cortado = OFF).

## Cambios por archivo

| Archivo | Cambio |
|---|---|
| `Motomami-esp32/Motomami-input-esp32c6/src/main.c` | `#include esp_now.h`, init ESP-NOW + broadcast peer + canal 6 tras `esp_wifi_start()`, `espnow_send_state()` en cada cambio de pin y cada 150 ms, SW WDT. MQTT intacto. |
| `Motomami-esp32/Motomami-direccionales-esp32c6/main/main.c` | `#include esp_now.h`, init ESP-NOW + callback de recepción + canal 6, SW WDT, timeout en `rmt_tx_wait_all_done`, quitar suscripciones MQTT a los 5 topics de control (quedan los 2 de intensidad). |
| `src/services/mqtt_listener.py` | Sin cambios. |
| `.agents/rules/memory.md` | Actualizar al cierre de la sesión. |

## Decision Log

| # | Decisión | Alternativas | Por qué |
|---|---|---|---|
| 1 | Control input→direccionales por **ESP-NOW broadcast**; MQTT solo para status/telemetría RPi | MQTT puro (actual), unicast con ACK, solo ESP-NOW | Quita a la RPi del camino de control; MQTT es best-effort para el monitor; a <2 m el broadcast es fiable (unicast con ACK = complejidad extra innecesaria, YAGNI) |
| 2 | Payload legible `"<msg_id>:LLLLL"` (5 chars) | Bitmask binario de 1-2 bytes, string `L:R:E:B:N` | Mismo formato que `motomami-input/data` (reutiliza parser mental y debug legible en serie); overhead irrelevante |
| 3 | Refresco **150 ms** + envío inmediato al cambiar pin | 300 ms (ritmo actual), 50 ms | 150 ms es la latencia máxima tolerable para luces sin sentirse lenta; 50 ms gasta radio sin beneficio |
| 4 | Canal WiFi **6** fijo en ambos STA | Canal por defecto | Coincide con Motomami-net; ESP-NOW funciona sin AP asociado |
| 5 | Sin enlace → **mantener último estado** | Apagar intermitentes y mantener frenado; todo OFF | El usuario prioriza no perder la luz de freno ni comportamientos inesperados; el SW WDT del input cubre el caso de emisor muerto |
| 6 | **SW WDT** con `esp_restart()` en ambos firmwares | Task WDT de IDF, reinicio manual | Task WDT no dispara con tareas bloqueadas en semáforo; no hay reinicio manual posible en calle |
| 7 | Timeout en `rmt_tx_wait_all_done` (500 ms) → restart | `portMAX_DELAY` (actual) | RMT atascado = luz congelada; con timeout el sistema se auto-recupera |
| 8 | El direccionales deja de suscribirse a los 5 topics MQTT de control | Mantener ambas entradas | ESP-NOW y MQTT controlarían los mismos flags con fuente distinta; ESP-NOW gana siempre (misma info), menos código |
| 9 | Velocímetro y OTA **fuera de alcance** | Incluirlos | El velocímetro no puede ir por ESP-NOW (destino RPi); OTA no cambia |

## Riesgos

- **ESP-NOW en ESP32-C6 con IDF 5.x/6.x**: soportado en STA; validar en banco que coexiste con WiFi (transmisión no degrada el refresco 150 ms).
- **Canal**: si algún día se cambia el canal del AP Motomami-net, hay que actualizar `ESPNOW_CHANNEL` en ambos firmwares.
- **Seguridad**: ESP-NOW sin cifrado; a bordo de la moto el riesgo es despreciable (no hay superficie de ataque razonable).
