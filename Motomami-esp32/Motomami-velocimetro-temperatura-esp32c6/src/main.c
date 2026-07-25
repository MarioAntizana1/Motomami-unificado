#include <stdio.h>
#include <string.h>
#include <math.h>
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

#define WIFI_SSID           "Motomami-net"
#define WIFI_PASS           "ktiarts123+++++/"
#define BROKER_URI          "mqtt://192.168.42.1:1883"

#define SENSOR_PIN          GPIO_NUM_21
#define TAG                 "VELOCIMETRO"
#define DEBOUNCE_US         2000        /* 2 ms reales via esp_timer (IRAM-safe) */
#define PULSES_PER_REV      3
#define WHEEL_DIAMETER_CM   43.0f
#define SPEED_TIMEOUT_MS    3000
#define MQTT_INTERVAL_MS    300
#define NVS_SAVE_PULSES     250
#define RSSI_INTERVAL_MS    21000
#define WIFI_RETRY_US       (1000 * 1000)   /* backoff 1 s reconexion WiFi */
#define MQTT_RECONNECT_MS   1000            /* reconexion MQTT rapida */

#define TOPIC_DATA          "motomami/velocimetro/data"
#define TOPIC_ODO           "motomami/velocimetro/odometro"
#define TOPIC_STATUS        "motomami/velocimetro/status"
#define TOPIC_IP            "motomami/velocimetro/ip"
#define TOPIC_RSSI          "motomami/velocimetro/rssi"
#define TOPIC_ID            "motomami/velocimetro/id"

#define DIST_PER_PULSE      (float)((M_PI * WHEEL_DIAMETER_CM) / (100.0f * PULSES_PER_REV))
#define SPEED_FACTOR        (float)(12.0f * M_PI * WHEEL_DIAMETER_CM)

#define NVS_NS              "velocimetro"
#define NVS_KEY             "pulses"

typedef enum {
    WAITING_RISING,
    WAITING_FALLING,
} pulse_state_t;

static esp_mqtt_client_handle_t mqtt_client = NULL;
static EventGroupHandle_t mqtt_group = NULL;
static esp_timer_handle_t wifi_retry_timer = NULL;

static volatile pulse_state_t pulse_state = WAITING_RISING;
static volatile uint32_t pulse_count = 0;
static volatile bool pulse_ready = false;
static volatile int64_t last_edge_us = 0;
static volatile int64_t last_pulse_us = 0;      /* timestamp del ultimo pulso contado */
static volatile uint32_t pulse_period_ms = 0;   /* periodo entre los 2 ultimos pulsos */

static uint32_t nvs_offset = 0;
static uint32_t last_saved = 0;
static uint32_t msg_id = 0;
static bool stopped_saved = true;               /* arranca "guardado" (NVS recien cargado) */
static char ip_str[16] = {0};

/* ==================================================================
 * ISR — debounce real de 2 ms con esp_timer (funciona en IRAM) y
 * medicion del periodo entre pulsos consecutivos contados.
 * ================================================================== */
static void IRAM_ATTR sensor_isr(void *arg) {
    int64_t now = esp_timer_get_time();

    if ((now - last_edge_us) < DEBOUNCE_US) {
        return;
    }
    last_edge_us = now;

    int level = gpio_get_level(SENSOR_PIN);

    if (level == 1) {
        if (pulse_state == WAITING_RISING) {
            pulse_state = WAITING_FALLING;
        }
    } else {
        if (pulse_state == WAITING_FALLING) {
            pulse_state = WAITING_RISING;
            pulse_count++;
            if (last_pulse_us > 0) {
                pulse_period_ms = (uint32_t)((now - last_pulse_us) / 1000);
            }
            last_pulse_us = now;
            pulse_ready = true;
        }
    }
}

static uint32_t load_nvs(void) {
    nvs_handle_t h;
    uint32_t val = 0;
    if (nvs_open(NVS_NS, NVS_READONLY, &h) == ESP_OK) {
        nvs_get_u32(h, NVS_KEY, &val);
        nvs_close(h);
    }
    return val;
}

static void save_nvs(uint32_t total) {
    nvs_handle_t h;
    if (nvs_open(NVS_NS, NVS_READWRITE, &h) == ESP_OK) {
        nvs_set_u32(h, NVS_KEY, total);
        nvs_commit(h);
        nvs_close(h);
        ESP_LOGI(TAG, "Odometro guardado en NVS: %lu pulsos", total);
    }
}

static uint32_t total_pulses(void) {
    return nvs_offset + pulse_count;
}

static void publish(const char *topic, const char *data, int len, int qos, bool retain) {
    if (mqtt_client && (xEventGroupGetBits(mqtt_group) & 1)) {
        esp_mqtt_client_publish(mqtt_client, topic, data, len, qos, retain ? 1 : 0);
    }
}

/* Velocidad actual en km/h.
 * Usa el periodo medido entre los dos ultimos pulsos (lo guarda el ISR).
 * Si la rueda desacelera (el tiempo desde el ultimo pulso supera al
 * periodo) la lectura decae suavemente; sin pulsos por SPEED_TIMEOUT_MS
 * la velocidad es 0. Sin pulsos desde el boot -> 0 (sin fantasma). */
static float current_speed(void) {
    int64_t last = last_pulse_us;
    if (last == 0) {
        return 0.0f;
    }
    int64_t since_ms = (esp_timer_get_time() - last) / 1000;
    if (since_ms >= SPEED_TIMEOUT_MS) {
        return 0.0f;
    }
    uint32_t period = pulse_period_ms;
    if (period == 0) {
        return 0.0f;   /* un solo pulso: aun no hay periodo medible */
    }
    uint32_t effective = (since_ms > (int64_t)period) ? (uint32_t)since_ms : period;
    return SPEED_FACTOR / (float)effective;
}

static void publish_data(void) {
    uint32_t total = total_pulses();
    float dist_km = total * DIST_PER_PULSE / 1000.0f;
    float speed = current_speed();

    char payload[96];
    snprintf(payload, sizeof(payload), "{\"id\":%lu,\"s\":%.1f,\"d\":%.3f,\"p\":%lu}",
             ++msg_id, speed, dist_km, total);
    publish(TOPIC_DATA, payload, -1, 0, false);
}

static void publish_rssi_id(void) {
    wifi_ap_record_t ap;
    if (esp_wifi_sta_get_ap_info(&ap) == ESP_OK) {
        char rssi_str[8];
        snprintf(rssi_str, sizeof(rssi_str), "%d", ap.rssi);
        publish(TOPIC_RSSI, rssi_str, -1, 0, true);
    }
    char id_str[12];
    snprintf(id_str, sizeof(id_str), "%lu", msg_id);
    publish(TOPIC_ID, id_str, -1, 0, true);
}

static void rssi_timer_cb(TimerHandle_t tmr) {
    publish_rssi_id();
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
        ESP_LOGI(TAG, "MQTT conectado a %s", BROKER_URI);
        xEventGroupSetBits(mqtt_group, 1);

        esp_mqtt_client_publish(mqtt_client, TOPIC_STATUS, "online", -1, 1, 1);

        uint32_t total = total_pulses();
        float dist_km = total * DIST_PER_PULSE / 1000.0f;
        char odo[16];
        snprintf(odo, sizeof(odo), "%.3f", dist_km);
        esp_mqtt_client_publish(mqtt_client, TOPIC_ODO, odo, -1, 1, 1);

        esp_mqtt_client_publish(mqtt_client, TOPIC_IP, ip_str, -1, 1, 1);

        publish_rssi_id();
    } else if (ev->event_id == MQTT_EVENT_DISCONNECTED) {
        ESP_LOGW(TAG, "MQTT desconectado");
        xEventGroupClearBits(mqtt_group, 1);
    }
}

void app_main(void) {
    ESP_LOGI(TAG, "=== VELOCIMETRO MQTT ===");
    ESP_LOGI(TAG, "GPIO21  %d pulsos/rev  diametro %.1fcm", PULSES_PER_REV, WHEEL_DIAMETER_CM);

    nvs_flash_init();
    nvs_offset = load_nvs();
    ESP_LOGI(TAG, "Odometro cargado: %lu pulsos (%.3f km)",
             nvs_offset, nvs_offset * DIST_PER_PULSE / 1000.0f);

    ota_boot_init();   /* auto-validacion anti-rollback (30 s) */

    esp_netif_init();
    esp_event_loop_create_default();

    mqtt_group = xEventGroupCreate();

    /* Sensor: ISR desde el arranque para no perder pulsos */
    gpio_reset_pin(SENSOR_PIN);
    gpio_config_t io = {
        .intr_type = GPIO_INTR_ANYEDGE,
        .mode = GPIO_MODE_INPUT,
        .pin_bit_mask = (1ULL << SENSOR_PIN),
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
    };
    gpio_config(&io);
    /* Estado inicial coherente con el nivel real del pin */
    pulse_state = (gpio_get_level(SENSOR_PIN) == 1) ? WAITING_FALLING : WAITING_RISING;
    /* ISR en IRAM: no se pierden pulsos durante escrituras NVS/flash */
    gpio_install_isr_service(ESP_INTR_FLAG_IRAM);
    gpio_isr_handler_add(SENSOR_PIN, sensor_isr, NULL);

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
            .ssid = WIFI_SSID,
            .password = WIFI_PASS,
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

    ESP_LOGI(TAG, "Sistema iniciado (no bloqueante) - contando pulsos desde ya");

    while (1) {
        if (pulse_ready) {
            pulse_ready = false;
            stopped_saved = false;

            uint32_t cur = pulse_count;
            if ((cur - last_saved) >= NVS_SAVE_PULSES) {
                save_nvs(nvs_offset + cur);
                last_saved = cur;
            }
        }

        /* Guardado unico al detectar detencion (sin spam de log/NVS) */
        if (!stopped_saved) {
            int64_t since_ms = (esp_timer_get_time() - last_pulse_us) / 1000;
            if (since_ms >= SPEED_TIMEOUT_MS) {
                save_nvs(nvs_offset + pulse_count);
                last_saved = pulse_count;
                stopped_saved = true;
                ESP_LOGI(TAG, "DETENIDO - odometro guardado");
            }
        }

        static uint32_t last_mqtt = 0;
        uint32_t now = xTaskGetTickCount();
        if ((now - last_mqtt) >= pdMS_TO_TICKS(MQTT_INTERVAL_MS)) {
            last_mqtt = now;
            publish_data();   /* se auto-suprime si MQTT esta caido */
        }

        vTaskDelay(pdMS_TO_TICKS(10));
    }
}
