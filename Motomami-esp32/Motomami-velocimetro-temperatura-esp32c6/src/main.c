/*
 * Velocimetro MQTT para MotoMami.
 *
 * Sensor Hall: GPIO21, activo en LOW y validado al volver a HIGH.
 * Rueda 3.50-10: diametro nominal 43.18 cm, 3 pulsos por revolucion.
 * OTA: ota_server.c mantiene POST /ota disponible en la red Motomami-net.
 */
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/task.h"
#include "freertos/timers.h"
#include "driver/gpio.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_ota_ops.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "mqtt_client.h"
#include "nvs.h"
#include "nvs_flash.h"
#include "ota_server.h"

#define WIFI_SSID "Motomami-net"
#define WIFI_PASS "ktiarts123+++++/"
#define BROKER_URI "mqtt://192.168.42.1:1883"

#define SENSOR_PIN GPIO_NUM_21
#define LED_PIN GPIO_NUM_15

#define TAG "VELOCIMETRO"
#define PI_F 3.14159265358979323846f

/* Sensor y rueda */
#define PULSES_PER_REV 3U
#define WHEEL_DIAMETER_CM 43.18f
#define MIN_LOW_US 20000LL
#define MIN_HIGH_US 8000LL
#define MIN_PULSE_GAP_US 10000LL

/* Telemetria */
#define SPEED_TIMEOUT_MS 3000LL
#define MQTT_INTERVAL_MS 200
#define RSSI_INTERVAL_MS 10000
#define NVS_SAVE_PULSES 250U
#define WIFI_RETRY_US 1000000LL
#define MQTT_RECONNECT_MS 1000

/* Topics existentes consumidos por monitor-mqtt */
#define TOPIC_DATA "motomami/velocimetro/data"
#define TOPIC_DEBUG "motomami/velocimetro/debug"
#define TOPIC_ODO "motomami/velocimetro/odometro"
#define TOPIC_STATUS "motomami/velocimetro/status"
#define TOPIC_IP "motomami/velocimetro/ip"
#define TOPIC_RSSI "motomami/velocimetro/rssi"
#define TOPIC_ID "motomami/velocimetro/id"

#define NVS_NAMESPACE "velocimetro"
#define NVS_KEY_PULSES "pulses"

static const float wheel_circumference_m = PI_F * (WHEEL_DIAMETER_CM / 100.0f);
static const float distance_per_pulse_m =
    (PI_F * (WHEEL_DIAMETER_CM / 100.0f)) / (float)PULSES_PER_REV;

static esp_mqtt_client_handle_t mqtt_client = NULL;
static EventGroupHandle_t mqtt_group = NULL;
static esp_timer_handle_t wifi_retry_timer = NULL;
static char ip_str[16] = {0};

/* Estado del sensor, compartido con la ISR */
static volatile uint32_t pulse_count = 0;
static volatile bool pulse_ready = false;
static int64_t last_pulse_us = 0;
static uint32_t pulse_period_us = 0;

typedef enum {
    SENSOR_HIGH_STABLE,
    SENSOR_LOW_CANDIDATE,
    SENSOR_LOW_STABLE,
    SENSOR_HIGH_CANDIDATE,
} sensor_state_t;

static sensor_state_t sensor_state = SENSOR_HIGH_STABLE;
static int64_t sensor_state_since_us = 0;

/* Estado persistente y MQTT */
static uint32_t nvs_offset = 0;
static uint32_t last_saved_pulses = 0;
static uint32_t message_id = 0;
static bool stopped_saved = true;

static uint32_t total_pulses(void)
{
    return nvs_offset + pulse_count;
}

static float total_distance_m(void)
{
    return (float)total_pulses() * distance_per_pulse_m;
}

static float total_distance_km(void)
{
    return total_distance_m() / 1000.0f;
}

/*
 * Filtro de estados ejecutado cada 1 ms:
 * - LOW debe durar 20 ms para ser una activacion valida.
 * - HIGH debe durar 8 ms para cerrar el pulso.
 * - Un cambio corto vuelve al estado anterior y no cuenta.
 */
static void sample_sensor(int level, int64_t now)
{
    switch (sensor_state) {
    case SENSOR_HIGH_STABLE:
        if (level == 0) {
            sensor_state = SENSOR_LOW_CANDIDATE;
            sensor_state_since_us = now;
        }
        break;

    case SENSOR_LOW_CANDIDATE:
        if (level == 1) {
            /* LOW corto: ruido, no iniciar un pulso. */
            sensor_state = SENSOR_HIGH_STABLE;
            sensor_state_since_us = now;
        } else if ((now - sensor_state_since_us) >= MIN_LOW_US) {
            sensor_state = SENSOR_LOW_STABLE;
        }
        break;

    case SENSOR_LOW_STABLE:
        if (level == 1) {
            sensor_state = SENSOR_HIGH_CANDIDATE;
            sensor_state_since_us = now;
        }
        break;

    case SENSOR_HIGH_CANDIDATE:
        if (level == 0) {
            /* HIGH corto: rebote, sigue siendo el mismo LOW. */
            sensor_state = SENSOR_LOW_STABLE;
        } else if ((now - sensor_state_since_us) >= MIN_HIGH_US) {
            const int64_t pulse_at = sensor_state_since_us;
            const int64_t gap = pulse_at - last_pulse_us;

            if (last_pulse_us == 0 || gap >= MIN_PULSE_GAP_US) {
                if (last_pulse_us > 0 && gap <= UINT32_MAX) {
                    const uint32_t sample_period = (uint32_t)gap;
                    if (pulse_period_us == 0) {
                        pulse_period_us = sample_period;
                    } else {
                        /* Media movil simple: reduce saltos de velocidad. */
                        pulse_period_us = (pulse_period_us * 3U + sample_period) / 4U;
                    }
                }
                last_pulse_us = pulse_at;
                pulse_count++;
                pulse_ready = true;
            }
            sensor_state = SENSOR_HIGH_STABLE;
            sensor_state_since_us = now;
        }
        break;
    }
}

static uint32_t load_nvs_pulses(void)
{
    nvs_handle_t handle;
    uint32_t value = 0;

    if (nvs_open(NVS_NAMESPACE, NVS_READONLY, &handle) == ESP_OK) {
        nvs_get_u32(handle, NVS_KEY_PULSES, &value);
        nvs_close(handle);
    }
    return value;
}

static void save_nvs_pulses(uint32_t total)
{
    nvs_handle_t handle;
    if (nvs_open(NVS_NAMESPACE, NVS_READWRITE, &handle) != ESP_OK) {
        ESP_LOGE(TAG, "No se pudo abrir NVS para guardar odometro");
        return;
    }

    esp_err_t err = nvs_set_u32(handle, NVS_KEY_PULSES, total);
    if (err == ESP_OK) {
        err = nvs_commit(handle);
    }
    nvs_close(handle);

    if (err == ESP_OK) {
        ESP_LOGI(TAG, "Odometro guardado: %lu pulsos (%.3f km)",
                 (unsigned long)total, total * distance_per_pulse_m / 1000.0f);
    } else {
        ESP_LOGE(TAG, "Error guardando NVS: %s", esp_err_to_name(err));
    }
}

static void publish_topic(const char *topic, const char *payload, int qos, bool retain)
{
    if (mqtt_client != NULL && mqtt_group != NULL &&
        (xEventGroupGetBits(mqtt_group) & 1U) != 0U) {
        esp_mqtt_client_publish(mqtt_client, topic, payload, -1, qos, retain ? 1 : 0);
    }
}

static float current_speed_kmh(void)
{
    const int64_t last = last_pulse_us;
    const uint32_t period = pulse_period_us;

    if (last == 0 || period == 0) {
        return 0.0f;
    }

    const int64_t elapsed = esp_timer_get_time() - last;
    if (elapsed >= SPEED_TIMEOUT_MS * 1000LL) {
        return 0.0f;
    }

    const int64_t effective_period = elapsed > (int64_t)period ? elapsed : period;
    return (distance_per_pulse_m * 3600000000.0f) / (float)effective_period;
}

static void publish_data(void)
{
    const uint32_t total = total_pulses();
    const float meters = total_distance_m();
    const float kilometers = meters / 1000.0f;
    const float speed = current_speed_kmh();
    char payload[160];

    snprintf(payload, sizeof(payload),
             "{\"id\":%lu,\"s\":%.1f,\"d\":%.3f,\"m\":%.1f,\"o\":%.3f,\"p\":%lu,\"dt\":%lu}",
             (unsigned long)++message_id, speed, kilometers, meters,
             kilometers, (unsigned long)total,
             (unsigned long)(pulse_period_us / 1000U));
    publish_topic(TOPIC_DATA, payload, 0, false);
}

static void publish_odometer(void)
{
    char payload[24];
    snprintf(payload, sizeof(payload), "%.3f", total_distance_km());
    publish_topic(TOPIC_ODO, payload, 1, true);
}

static void publish_rssi_id(void)
{
    wifi_ap_record_t ap;
    if (esp_wifi_sta_get_ap_info(&ap) == ESP_OK) {
        char rssi[12];
        snprintf(rssi, sizeof(rssi), "%d", ap.rssi);
        publish_topic(TOPIC_RSSI, rssi, 1, true);
    }

    char id[16];
    snprintf(id, sizeof(id), "%lu", (unsigned long)message_id);
    publish_topic(TOPIC_ID, id, 1, true);
}

static void rssi_timer_callback(TimerHandle_t timer)
{
    (void)timer;
    publish_rssi_id();
}

static void start_mqtt(void);

static void wifi_retry_callback(void *arg)
{
    (void)arg;
    esp_wifi_connect();
}

static void wifi_event_handler(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg;

    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        ESP_LOGI(TAG, "WiFi iniciado, conectando a %s", WIFI_SSID);
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_CONNECTED) {
        ESP_LOGI(TAG, "WiFi asociado a Motomami-net");
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        ESP_LOGW(TAG, "WiFi desconectado, reintento en 1 s");
        if (wifi_retry_timer != NULL) {
            esp_timer_stop(wifi_retry_timer);
            esp_timer_start_once(wifi_retry_timer, WIFI_RETRY_US);
        }
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *event = (ip_event_got_ip_t *)data;
        esp_ip4addr_ntoa(&event->ip_info.ip, ip_str, sizeof(ip_str));
        ESP_LOGI(TAG, "WiFi OK - IP %s", ip_str);
        start_mqtt();
        ota_server_start();
    }
}

static void mqtt_event_handler(void *args, esp_event_base_t base, int32_t id, void *data)
{
    (void)args;
    (void)base;
    esp_mqtt_event_handle_t event = (esp_mqtt_event_handle_t)data;

    if (event->event_id == MQTT_EVENT_CONNECTED) {
        ESP_LOGI(TAG, "MQTT conectado a %s", BROKER_URI);
        xEventGroupSetBits(mqtt_group, 1U);
        publish_topic(TOPIC_STATUS, "online", 1, true);
        publish_odometer();
        publish_topic(TOPIC_IP, ip_str, 1, true);
        publish_rssi_id();
        publish_data();
    } else if (event->event_id == MQTT_EVENT_DISCONNECTED) {
        ESP_LOGW(TAG, "MQTT desconectado");
        xEventGroupClearBits(mqtt_group, 1U);
    }
}

static void start_mqtt(void)
{
    if (mqtt_client != NULL) {
        return;
    }

    esp_mqtt_client_config_t config = {
        .broker = {.address = {.uri = BROKER_URI}},
        .network = {.reconnect_timeout_ms = MQTT_RECONNECT_MS},
        .session = {.last_will = {
            .topic = TOPIC_STATUS,
            .msg = "offline",
            .qos = 1,
            .retain = true,
        }},
    };

    mqtt_client = esp_mqtt_client_init(&config);
    esp_mqtt_client_register_event(mqtt_client, ESP_EVENT_ANY_ID,
                                   mqtt_event_handler, mqtt_client);
    esp_mqtt_client_start(mqtt_client);
}

void app_main(void)
{
    ESP_LOGI(TAG, "=== VELOCIMETRO MQTT ===");
    ESP_LOGI(TAG, "GPIO21 | 3 pulsos/rev | rueda 3.50-10 | diametro %.2f cm",
             WHEEL_DIAMETER_CM);
    ESP_LOGI(TAG, "Circunferencia %.3f m | %.3f m/pulso | MQTT cada %d ms",
             wheel_circumference_m, distance_per_pulse_m, MQTT_INTERVAL_MS);

    esp_err_t nvs_err = nvs_flash_init();
    if (nvs_err == ESP_ERR_NVS_NO_FREE_PAGES || nvs_err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ESP_ERROR_CHECK(nvs_flash_init());
    }

    nvs_offset = load_nvs_pulses();
    ESP_LOGI(TAG, "Odometro cargado: %lu pulsos (%.3f km)",
             (unsigned long)nvs_offset, nvs_offset * distance_per_pulse_m / 1000.0f);

    ota_boot_init();
    esp_netif_init();
    esp_event_loop_create_default();
    mqtt_group = xEventGroupCreate();

    gpio_reset_pin(SENSOR_PIN);
    gpio_config_t sensor_config = {
        .intr_type = GPIO_INTR_ANYEDGE,
        .mode = GPIO_MODE_INPUT,
        .pin_bit_mask = (1ULL << SENSOR_PIN),
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
    };
    ESP_ERROR_CHECK(gpio_config(&sensor_config));

    const int initial_level = gpio_get_level(SENSOR_PIN);
    sensor_state = initial_level == 0 ? SENSOR_LOW_CANDIDATE : SENSOR_HIGH_STABLE;
    sensor_state_since_us = esp_timer_get_time();

    /* El LED refleja directamente el nivel del sensor, como en el debug. */
    gpio_config_t led_config = {
        .intr_type = GPIO_INTR_DISABLE,
        .mode = GPIO_MODE_OUTPUT,
        .pin_bit_mask = (1ULL << LED_PIN),
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
    };
    ESP_ERROR_CHECK(gpio_config(&led_config));
    gpio_set_level(LED_PIN, initial_level);

    ESP_LOGI(TAG, "Sensor listo. Nivel inicial GPIO21=%d", initial_level);

    esp_netif_create_default_wifi_sta();
    wifi_init_config_t wifi_init = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&wifi_init));

    /* RF switch de la antena externa u.FL del XIAO C6. */
    gpio_set_direction(GPIO_NUM_14, GPIO_MODE_OUTPUT);
    gpio_set_level(GPIO_NUM_14, 1);
    esp_wifi_set_max_tx_power(40);

    ESP_ERROR_CHECK(esp_event_handler_instance_register(
        WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event_handler, NULL, NULL));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(
        IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_event_handler, NULL, NULL));

    const esp_timer_create_args_t retry_args = {
        .callback = wifi_retry_callback,
        .name = "wifi_retry",
    };
    ESP_ERROR_CHECK(esp_timer_create(&retry_args, &wifi_retry_timer));

    wifi_config_t wifi_config = {
        .sta = {
            .ssid = WIFI_SSID,
            .password = WIFI_PASS,
        },
    };
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
    ESP_ERROR_CHECK(esp_wifi_start());

    TimerHandle_t rssi_timer = xTimerCreate(
        "rssi_timer", pdMS_TO_TICKS(RSSI_INTERVAL_MS), pdTRUE, NULL,
        rssi_timer_callback);
    if (rssi_timer != NULL) {
        xTimerStart(rssi_timer, 0);
    }

    ESP_LOGI(TAG, "Sistema iniciado; odometro persistente y OTA activos");

    TickType_t last_mqtt = xTaskGetTickCount();
    TickType_t last_debug = last_mqtt;

    while (true) {
        const int64_t now_us = esp_timer_get_time();
        const int pin_level = gpio_get_level(SENSOR_PIN);
        sample_sensor(pin_level, now_us);
        gpio_set_level(LED_PIN, pin_level);

        bool pulse_event = pulse_ready;
        if (pulse_event) {
            pulse_ready = false;
            stopped_saved = false;
            ESP_LOGI(TAG, "PULSO total=%lu velocidad=%.1f km/h",
                     (unsigned long)total_pulses(), current_speed_kmh());
        }

        const int64_t last = last_pulse_us;
        if (!stopped_saved && last > 0 &&
            (esp_timer_get_time() - last) >= SPEED_TIMEOUT_MS * 1000LL) {
            save_nvs_pulses(total_pulses());
            last_saved_pulses = pulse_count;
            stopped_saved = true;
        }

        const uint32_t current = pulse_count;
        if ((current - last_saved_pulses) >= NVS_SAVE_PULSES) {
            save_nvs_pulses(total_pulses());
            last_saved_pulses = current;
        }

        const TickType_t now = xTaskGetTickCount();
        if (pulse_event || (now - last_mqtt) >= pdMS_TO_TICKS(MQTT_INTERVAL_MS)) {
            last_mqtt = now;
            publish_data();
        }

        if ((now - last_debug) >= pdMS_TO_TICKS(2000)) {
            last_debug = now;
            char debug[80];
            snprintf(debug, sizeof(debug), "{\"pin\":%d,\"pulses\":%lu}",
                     pin_level, (unsigned long)total_pulses());
            publish_topic(TOPIC_DEBUG, debug, 0, false);
        }

        vTaskDelay(pdMS_TO_TICKS(5));
    }
}
