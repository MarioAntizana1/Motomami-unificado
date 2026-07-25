#include <stdio.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/timers.h"
#include "freertos/event_groups.h"
#include "esp_system.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "nvs_flash.h"
#include "esp_netif.h"
#include "driver/gpio.h"
#include "mqtt_client.h"
#include "ota_server.h"

#define SSID                "Motomami-net"
#define PASS                "ktiarts123+++++/"
#define BROKER_URI          "mqtt://192.168.42.1"

#define INPUT_1             18
#define INPUT_2             2
#define INPUT_3             21
#define INPUT_4             22
#define INPUT_5             23

#define TOPIC_1             "motomami/intermitente_izquierda"
#define TOPIC_2             "motomami/intermitente_derecha"
#define TOPIC_3             "motomami/intermitente_emergencia"
#define TOPIC_4             "motomami/frenado"
#define TOPIC_5             "motomami/luz_nocturna"
#define TOPIC_STATUS        "motomami-input/status"
#define TOPIC_IP            "motomami-input/status/ip"
#define TOPIC_RSSI          "motomami-input/status/rssi"
#define TOPIC_ID            "motomami-input/status/id"

#define PIN_COUNT           5
#define DEBOUNCE_MS         50
#define POLL_MS             10
#define RSSI_INTERVAL_MS    21000
#define STATE_PRINT_MS      5000
#define WIFI_RETRY_US       (1000 * 1000)   /* backoff 1 s reconexion WiFi */
#define MQTT_RECONNECT_MS   1000            /* reconexion MQTT rapida */
#define BUF_CAP             32              /* mensajes pendientes con MQTT caido */

static const char *TAG = "MOTOMAMI";
static esp_mqtt_client_handle_t mqtt_client = NULL;
static EventGroupHandle_t mqtt_group = NULL;
static esp_timer_handle_t wifi_retry_timer = NULL;

static const int pins[PIN_COUNT]  = {INPUT_1, INPUT_2, INPUT_3, INPUT_4, INPUT_5};
static const int pin_labels[PIN_COUNT] = {10, 2, 3, 4, 5};
static const char *topics[PIN_COUNT] = {TOPIC_1, TOPIC_2, TOPIC_3, TOPIC_4, TOPIC_5};

static int last_reading[PIN_COUNT];
static int current_state[PIN_COUNT];
static TickType_t last_debounce_time[PIN_COUNT];
static char ip_str[16] = {0};
static char rssi_status[8] = "0";

/* ----------------------------------------------------------------
 * Buffer circular de mensajes pendientes (MQTT caido).
 * Cada mensaje recibe un id al encolarse: si el buffer se llena y se
 * descarta el mas viejo, la RPi detecta el hueco en la secuencia.
 * ---------------------------------------------------------------- */
typedef struct {
    uint8_t pin;
    uint8_t state;
    uint32_t id;
} pending_msg_t;

static pending_msg_t pending[BUF_CAP];
static int buf_head = 0;   /* escritura */
static int buf_tail = 0;   /* lectura   */
static portMUX_TYPE buf_mux = portMUX_INITIALIZER_UNLOCKED;
static uint32_t msg_id = 0;

static void buffer_push(int pin, int state) {
    portENTER_CRITICAL(&buf_mux);
    uint32_t id = ++msg_id;
    int next = (buf_head + 1) % BUF_CAP;
    if (next == buf_tail) {
        buf_tail = (buf_tail + 1) % BUF_CAP;   /* lleno: descarta el mas viejo */
        ESP_LOGW(TAG, "Buffer lleno: mensaje viejo descartado (id perdido)");
    }
    pending[buf_head].pin = (uint8_t)pin;
    pending[buf_head].state = (uint8_t)state;
    pending[buf_head].id = id;
    buf_head = next;
    portEXIT_CRITICAL(&buf_mux);
}

/* Publica y libera los mensajes pendientes en orden (FIFO) */
static void buffer_flush(void) {
    while (mqtt_client && (xEventGroupGetBits(mqtt_group) & 1)) {
        portENTER_CRITICAL(&buf_mux);
        if (buf_tail == buf_head) {
            portEXIT_CRITICAL(&buf_mux);
            return;
        }
        pending_msg_t m = pending[buf_tail];
        buf_tail = (buf_tail + 1) % BUF_CAP;
        portEXIT_CRITICAL(&buf_mux);

        char payload[24];
        snprintf(payload, sizeof(payload), "%lu:%s", m.id, m.state ? "OFF" : "ON");
        esp_mqtt_client_publish(mqtt_client, topics[m.pin], payload, 0, 1, 1);
        ESP_LOGI(TAG, "  -> buffer: id=%lu %s en %s", m.id, m.state ? "OFF" : "ON", topics[m.pin]);
    }
}

static void publish(const char *topic, const char *data, int len, int qos, bool retain) {
    if (mqtt_client && (xEventGroupGetBits(mqtt_group) & 1)) {
        esp_mqtt_client_publish(mqtt_client, topic, data, len, qos, retain ? 1 : 0);
    }
}

static void publish_rssi_id(void) {
    wifi_ap_record_t ap;
    if (esp_wifi_sta_get_ap_info(&ap) == ESP_OK) {
        snprintf(rssi_status, sizeof(rssi_status), "%d", ap.rssi);
        publish(TOPIC_RSSI, rssi_status, -1, 0, true);
        ESP_LOGI(TAG, "RSSI: %d dBm", ap.rssi);
    }
    char id_str[12];
    snprintf(id_str, sizeof(id_str), "%lu", msg_id);
    publish(TOPIC_ID, id_str, -1, 0, true);
}

static void log_states(void) {
    for (int i = 0; i < PIN_COUNT; i++) {
        int level = gpio_get_level(pins[i]);
        ESP_LOGI(TAG, "  D%d (GPIO%d) = %s  |  %s",
                 pin_labels[i], pins[i], level ? "HIGH" : "LOW ", topics[i]);
    }
    ESP_LOGW(TAG, "---");
}

static void wifi_retry_cb(void *arg) {
    esp_wifi_connect();
}

static void wifi_event_handler(void *arg, esp_event_base_t base, int32_t id, void *data) {
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        ESP_LOGW(TAG, "WiFi desconectado, reintento en 1 s...");
        if (wifi_retry_timer) {
            esp_timer_start_once(wifi_retry_timer, WIFI_RETRY_US);
        }
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        if (wifi_retry_timer) {
            esp_timer_stop(wifi_retry_timer);
        }
        ip_event_got_ip_t *ev = (ip_event_got_ip_t *)data;
        esp_ip4addr_ntoa(&ev->ip_info.ip, ip_str, sizeof(ip_str));
        ESP_LOGI(TAG, "WiFi conectado - IP: %s", ip_str);
        ota_server_start();
    }
}

static void mqtt_event_handler(void *args, esp_event_base_t base, int32_t id, void *data) {
    esp_mqtt_event_handle_t ev = (esp_mqtt_event_handle_t)data;

    if (ev->event_id == MQTT_EVENT_CONNECTED) {
        ESP_LOGI(TAG, "MQTT conectado al broker %s", BROKER_URI);
        xEventGroupSetBits(mqtt_group, 1);

        esp_mqtt_client_publish(mqtt_client, TOPIC_STATUS, "online", -1, 1, 1);
        esp_mqtt_client_publish(mqtt_client, TOPIC_IP, ip_str, -1, 1, 1);

        /* 1) Liberar lo acumulado mientras no habia conexion */
        buffer_flush();

        /* 2) Sincronizar estado actual de los 5 pines (retained) */
        for (int i = 0; i < PIN_COUNT; i++) {
            buffer_push(i, current_state[i]);
        }
        buffer_flush();

        publish_rssi_id();
    } else if (ev->event_id == MQTT_EVENT_DISCONNECTED) {
        ESP_LOGW(TAG, "MQTT desconectado - acumulando en buffer");
        xEventGroupClearBits(mqtt_group, 1);
    }
}

static void print_states(void) {
    for (int i = 0; i < PIN_COUNT; i++) {
        int level = gpio_get_level(pins[i]);
        ESP_LOGI(TAG, "  D%d=%s", pin_labels[i], level ? "HIGH" : "LOW");
    }
}

static void input_task(void *pv) {
    TickType_t last = xTaskGetTickCount();
    TickType_t last_print = xTaskGetTickCount();
    while (1) {
        vTaskDelayUntil(&last, pdMS_TO_TICKS(POLL_MS));
        for (int i = 0; i < PIN_COUNT; i++) {
            int r = gpio_get_level(pins[i]);
            if (r != last_reading[i]) {
                last_debounce_time[i] = xTaskGetTickCount();
            }
            if ((xTaskGetTickCount() - last_debounce_time[i]) > pdMS_TO_TICKS(DEBOUNCE_MS)) {
                if (r != current_state[i]) {
                    current_state[i] = r;
                    ESP_LOGW(TAG, ">>> CAMBIO D%d: %s -> %s  | encolando %s en %s",
                             pin_labels[i],
                             r ? "LOW " : "HIGH",
                             r ? "HIGH" : "LOW ",
                             r ? "OFF" : "ON",
                             topics[i]);
                    /* Siempre se encola (con id); se libera al instante si hay MQTT */
                    buffer_push(i, r);
                    buffer_flush();
                }
            }
            last_reading[i] = r;
        }
        if ((xTaskGetTickCount() - last_print) >= pdMS_TO_TICKS(STATE_PRINT_MS)) {
            last_print = xTaskGetTickCount();
            ESP_LOGI(TAG, "--- Estados GPIO cada 5s ---");
            print_states();
        }
    }
}

static void rssi_timer_cb(TimerHandle_t tmr) {
    publish_rssi_id();
}

void app_main(void) {
    ESP_LOGI(TAG, "=== MOTOMAMI INPUT ESP32C6 ===");

    nvs_flash_init();
    esp_netif_init();
    esp_event_loop_create_default();

    mqtt_group = xEventGroupCreate();

    ota_boot_init();   /* auto-validacion anti-rollback (30 s) */

    const int all_pins[] = {INPUT_1, INPUT_2, INPUT_3, INPUT_4, INPUT_5};
    for (int i = 0; i < PIN_COUNT; i++) {
        gpio_reset_pin(all_pins[i]);
    }

    gpio_config_t gpio = {
        .intr_type = GPIO_INTR_DISABLE,
        .mode = GPIO_MODE_INPUT,
        .pin_bit_mask = (1ULL << INPUT_1) | (1ULL << INPUT_2) | (1ULL << INPUT_3) | (1ULL << INPUT_4) | (1ULL << INPUT_5),
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
    };
    gpio_config(&gpio);

    for (int i = 0; i < PIN_COUNT; i++) {
        last_reading[i] = gpio_get_level(pins[i]);
        current_state[i] = last_reading[i];
        last_debounce_time[i] = 0;
    }

    ESP_LOGI(TAG, "Estado inicial de las entradas opticas:");
    log_states();

    /* Controles activos desde ya: el input_task NO espera a WiFi ni a MQTT.
     * Los cambios se acumulan en el buffer y se liberan al conectar. */
    xTaskCreate(input_task, "input_task", 4096, NULL, 10, NULL);

    esp_netif_create_default_wifi_sta();
    wifi_init_config_t wcfg = WIFI_INIT_CONFIG_DEFAULT();
    esp_wifi_init(&wcfg);
    /* El AP (RPi) esta en la propia moto a <2 m: 10 dBm sobra.
     * Reduce el pico de corriente, el consumo y el calor. */
    esp_wifi_set_max_tx_power(40);
    esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event_handler, NULL, NULL);
    esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_event_handler, NULL, NULL);

    const esp_timer_create_args_t retry_args = {
        .callback = wifi_retry_cb,
        .name = "wifi_retry",
    };
    esp_timer_create(&retry_args, &wifi_retry_timer);

    wifi_config_t wificfg = {
        .sta = {
            .ssid = SSID,
            .password = PASS,
        },
    };
    esp_wifi_set_mode(WIFI_MODE_STA);
    esp_wifi_set_config(WIFI_IF_STA, &wificfg);
    esp_wifi_start();

    /* MQTT arranca de inmediato (no bloqueante): esp_mqtt reintenta solo */
    esp_mqtt_client_config_t mqttcfg = {
        .broker = {.address = {.uri = BROKER_URI}},
        .network = {.reconnect_timeout_ms = MQTT_RECONNECT_MS},
        .session = {.last_will = {
            .topic = TOPIC_STATUS,
            .msg = "offline",
            .qos = 1,
            .retain = true,
        }},
    };
    mqtt_client = esp_mqtt_client_init(&mqttcfg);
    esp_mqtt_client_register_event(mqtt_client, ESP_EVENT_ANY_ID, mqtt_event_handler, mqtt_client);
    esp_mqtt_client_start(mqtt_client);

    TimerHandle_t rssi_timer = xTimerCreate("rssi_tmr", pdMS_TO_TICKS(RSSI_INTERVAL_MS), pdTRUE, NULL, rssi_timer_cb);
    xTimerStart(rssi_timer, 0);

    ESP_LOGI(TAG, "Sistema iniciado (no bloqueante) - monitoreando %d entradas", PIN_COUNT);
}
