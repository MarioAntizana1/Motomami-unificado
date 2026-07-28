#include <string.h>
#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "driver/gpio.h"
#include "nvs_flash.h"
#include "esp_netif.h"
#include "esp_event.h"
#include "esp_wifi.h"
#include "esp_timer.h"
#include "mqtt_client.h"
#include "ota_server.h"

/* ================================================================
   WIFI / MQTT
   ================================================================ */
#define WIFI_SSID      "Motomami-net"
#define WIFI_PASS      "ktiarts123+++++/"
#define MQTT_BROKER    "mqtt://192.168.42.1"

#define WIFI_RETRY_US      (1000 * 1000)   /* backoff 1 s al reconectar WiFi */
#define MQTT_RECONNECT_MS  1000            /* reconexion MQTT rapida */

/* ================================================================
   ESTADO GLOBAL
   ================================================================ */
static const char *TAG = "input";

static esp_mqtt_client_handle_t mqtt_client;
static esp_netif_t *netif = NULL;
static esp_timer_handle_t wifi_retry_timer = NULL;

/* Contador de mensajes publicados (parametro de control "ID") */
static uint32_t msg_id = 0;

/* ================================================================
   GPIO INPUTS (5 entradas optoacopladas)
   ================================================================ */
#define INPUT_1             18
#define INPUT_2             2
#define INPUT_3             21
#define INPUT_4             22
#define INPUT_5             23
#define PIN_COUNT           5
#define DEBOUNCE_MS         50
#define POLL_MS             10
#define BUF_CAP             32

static const int in_pins[PIN_COUNT]  = {INPUT_1, INPUT_2, INPUT_3, INPUT_4, INPUT_5};
static const char *in_topics[PIN_COUNT] = {
    "motomami/intermitente_izquierda",
    "motomami/intermitente_derecha",
    "motomami/intermitente_emergencia",
    "motomami/frenado",
    "motomami/luz_nocturna",
};
static int in_last_reading[PIN_COUNT];
static int in_current_state[PIN_COUNT];
static TickType_t in_last_debounce[PIN_COUNT];

typedef struct { uint8_t pin; uint8_t state; uint32_t id; } pending_msg_t;
static pending_msg_t pending[BUF_CAP];
static int buf_head = 0, buf_tail = 0;
static portMUX_TYPE buf_mux = portMUX_INITIALIZER_UNLOCKED;

static void buffer_push(int pin, int state) {
    portENTER_CRITICAL(&buf_mux);
    uint32_t id = ++msg_id;
    int next = (buf_head + 1) % BUF_CAP;
    if (next == buf_tail) buf_tail = (buf_tail + 1) % BUF_CAP;
    pending[buf_head] = (pending_msg_t){ .pin = (uint8_t)pin, .state = (uint8_t)state, .id = id };
    buf_head = next;
    portEXIT_CRITICAL(&buf_mux);
}

static void buffer_flush(void) {
    while (mqtt_client) {
        portENTER_CRITICAL(&buf_mux);
        if (buf_tail == buf_head) { portEXIT_CRITICAL(&buf_mux); return; }
        pending_msg_t m = pending[buf_tail];
        buf_tail = (buf_tail + 1) % BUF_CAP;
        portEXIT_CRITICAL(&buf_mux);
        char payload[24];
        snprintf(payload, sizeof(payload), "%lu:%s", m.id, m.state ? "OFF" : "ON");
        esp_mqtt_client_publish(mqtt_client, in_topics[m.pin], payload, 0, 1, 1);
    }
}

static void publish_all_state(void) {
    if (!mqtt_client) return;
    taskENTER_CRITICAL(&buf_mux);
    uint32_t id = ++msg_id;
    taskEXIT_CRITICAL(&buf_mux);
    char payload[16];
    snprintf(payload, sizeof(payload), "%lu:%d%d%d%d%d", id,
        gpio_get_level(in_pins[0]),
        gpio_get_level(in_pins[1]),
        gpio_get_level(in_pins[2]),
        gpio_get_level(in_pins[3]),
        gpio_get_level(in_pins[4]));
    esp_mqtt_client_publish(mqtt_client, "motomami-input/data", payload, 0, 1, 1);
}

static void input_task(void *pv) {
    TickType_t last = xTaskGetTickCount();
    TickType_t last_data_pub = 0;
    while (1) {
        vTaskDelayUntil(&last, pdMS_TO_TICKS(POLL_MS));
        TickType_t now = xTaskGetTickCount();
        if (now - last_data_pub >= pdMS_TO_TICKS(300)) {
            last_data_pub = now;
            publish_all_state();
        }
        for (int i = 0; i < PIN_COUNT; i++) {
            int r = gpio_get_level(in_pins[i]);
            if (r != in_last_reading[i]) in_last_debounce[i] = xTaskGetTickCount();
            if ((xTaskGetTickCount() - in_last_debounce[i]) > pdMS_TO_TICKS(DEBOUNCE_MS)) {
                if (r != in_current_state[i]) {
                    in_current_state[i] = r;
                    buffer_push(i, r);
                    buffer_flush();
                    publish_all_state();
                }
            }
            in_last_reading[i] = r;
        }
    }
}

/* ================================================================
   MQTT
   ================================================================ */
static void mqtt_event_handler(void *args, esp_event_base_t base, int32_t event_id, void *data)
{
    esp_mqtt_event_t *event = data;
    esp_mqtt_client_handle_t client = event->client;

    switch ((esp_mqtt_event_id_t)event_id) {
    case MQTT_EVENT_CONNECTED:
        ESP_LOGI(TAG, "MQTT connected");
        esp_mqtt_client_publish(client, "motomami-input/status", "online", 6, 1, true);

        {
            esp_netif_ip_info_t ip_info;
            if (netif && esp_netif_get_ip_info(netif, &ip_info) == ESP_OK) {
                char ip_str[16];
                sprintf(ip_str, IPSTR, IP2STR(&ip_info.ip));
                esp_mqtt_client_publish(client, "motomami-input/status/ip", ip_str, 0, 1, true);
                ESP_LOGI(TAG, "IP: %s", ip_str);
            }
        }

        {
            wifi_ap_record_t ap_info;
            if (esp_wifi_sta_get_ap_info(&ap_info) == ESP_OK) {
                char rssi_str[8];
                sprintf(rssi_str, "%d", ap_info.rssi);
                esp_mqtt_client_publish(client, "motomami-input/status/rssi", rssi_str, 0, 1, true);
                ESP_LOGI(TAG, "RSSI: %d", ap_info.rssi);
            }
        }

        /* Sincronizar estado actual de los 5 pines (retained) */
        buffer_flush();
        for (int i = 0; i < PIN_COUNT; i++) buffer_push(i, in_current_state[i]);
        buffer_flush();
        publish_all_state();

        {
            char id_str[12];
            sprintf(id_str, "%lu", msg_id);
            esp_mqtt_client_publish(client, "motomami-input/status/id", id_str, 0, 1, true);
        }
        break;

    case MQTT_EVENT_ERROR:
        ESP_LOGE(TAG, "MQTT error");
        break;

    default:
        break;
    }
}

static void start_mqtt(void)
{
    /* GOT_IP se dispara en cada reconexion WiFi: crear el cliente una sola vez.
     * esp_mqtt ya auto-reconecta por si solo. */
    if (mqtt_client != NULL) {
        return;
    }
    esp_mqtt_client_config_t mqtt_cfg = {
        .broker.address.uri = MQTT_BROKER,
        .network.reconnect_timeout_ms = MQTT_RECONNECT_MS,
        .session.last_will.topic = "motomami-input/status",
        .session.last_will.msg = "offline",
        .session.last_will.msg_len = 7,
        .session.last_will.qos = 1,
        .session.last_will.retain = true,
    };
    mqtt_client = esp_mqtt_client_init(&mqtt_cfg);
    esp_mqtt_client_register_event(mqtt_client, ESP_EVENT_ANY_ID, mqtt_event_handler, NULL);
    esp_mqtt_client_start(mqtt_client);
}

/* ================================================================
   WIFI
   ================================================================ */
static void wifi_retry_cb(void *arg)
{
    esp_wifi_connect();
}

static void wifi_event_handler(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    if (id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (id == WIFI_EVENT_STA_DISCONNECTED) {
        /* backoff corto para no reconectar en rafaga si el AP esta caido */
        ESP_LOGI(TAG, "WiFi caido, reintento en 1 s...");
        if (wifi_retry_timer) {
            esp_timer_start_once(wifi_retry_timer, WIFI_RETRY_US);
        }
    } else if (id == IP_EVENT_STA_GOT_IP) {
        if (wifi_retry_timer) {
            esp_timer_stop(wifi_retry_timer);
        }
        ESP_LOGI(TAG, "WiFi connected, starting MQTT + OTA...");
        start_mqtt();
        ota_server_start();
    }
}

static void wifi_init(void)
{
    esp_netif_init();
    esp_event_loop_create_default();
    netif = esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    esp_wifi_init(&cfg);

    /* Antena externa u.FL: GPIO14=HIGH activa el RF switch del XIAO C6 */
    gpio_set_direction(GPIO_NUM_14, GPIO_MODE_OUTPUT);
    gpio_set_level(GPIO_NUM_14, 1);

    /* El AP (RPi) esta en la propia moto a <2 m: 10 dBm sobra.
     * Reduce el pico de corriente (tambien en la calibracion RF),
     * el consumo y el calor. */
    esp_wifi_set_max_tx_power(40);

    esp_event_handler_instance_t instance_any;
    esp_event_handler_instance_t instance_got_ip;
    esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID, &wifi_event_handler, NULL, &instance_any);
    esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP, &wifi_event_handler, NULL, &instance_got_ip);

    const esp_timer_create_args_t retry_args = {
        .callback = wifi_retry_cb,
        .name = "wifi_retry",
    };
    esp_timer_create(&retry_args, &wifi_retry_timer);

    wifi_config_t wifi_config = {
        .sta = {
            .ssid = WIFI_SSID,
            .password = WIFI_PASS,
        },
    };
    esp_wifi_set_mode(WIFI_MODE_STA);
    esp_wifi_set_config(WIFI_IF_STA, &wifi_config);
    esp_wifi_start();

    ESP_LOGI(TAG, "WiFi connecting to %s...", WIFI_SSID);
}

/* ================================================================
   MAIN
   ================================================================ */
void app_main(void)
{
    ESP_ERROR_CHECK(nvs_flash_init());

    ota_boot_init();   // auto-validacion anti-rollback (30 s)

    /* GPIO inputs: activos desde el arranque */
    const int all_pins[] = {INPUT_1, INPUT_2, INPUT_3, INPUT_4, INPUT_5};
    for (int i = 0; i < PIN_COUNT; i++) gpio_reset_pin(all_pins[i]);
    gpio_config_t in_gpio = {
        .intr_type = GPIO_INTR_DISABLE, .mode = GPIO_MODE_INPUT,
        .pin_bit_mask = (1ULL<<INPUT_1)|(1ULL<<INPUT_2)|(1ULL<<INPUT_3)|(1ULL<<INPUT_4)|(1ULL<<INPUT_5),
        .pull_up_en = GPIO_PULLUP_ENABLE, .pull_down_en = GPIO_PULLDOWN_DISABLE,
    };
    gpio_config(&in_gpio);
    for (int i = 0; i < PIN_COUNT; i++) {
        in_last_reading[i] = in_current_state[i] = gpio_get_level(in_pins[i]);
        in_last_debounce[i] = 0;
    }
    xTaskCreate(input_task, "input_task", 4096, NULL, 10, NULL);

    wifi_init();

    ESP_LOGI(TAG, "Sistema iniciado - %d entradas", PIN_COUNT);
}
