/*
 * ota_server.c — Servidor HTTP OTA compartido (Motomami ESP32-C6)
 *
 * POST /ota  (header X-OTA-Token)  -> escribe la imagen en la siguiente
 * particion OTA, la marca como boot y reinicia.
 * GET /      -> info del modulo.
 *
 * Seguridad: el endpoint queda abierto en la red WiFi; el header
 * X-OTA-Token actua como token de validacion minimo.
 */
#include <string.h>
#include <stdlib.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "esp_app_format.h"
#include "esp_http_server.h"
#include "esp_ota_ops.h"
#include "sdkconfig.h"

#include "ota_server.h"

#define OTA_TOKEN       "motomami-ota-2026"
#define OTA_BUF_SIZE    2048
#define OTA_VALIDATE_MS 30000

static const char *TAG = "OTA";
static httpd_handle_t ota_httpd = NULL;

/* ----------------------------------------------------------------
 * Auto-validacion anti-rollback
 * ---------------------------------------------------------------- */
#if CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE
static void ota_validate_task(void *arg)
{
    vTaskDelay(pdMS_TO_TICKS(OTA_VALIDATE_MS));
    esp_err_t err = esp_ota_mark_app_valid_cancel_rollback();
    if (err == ESP_OK) {
        ESP_LOGI(TAG, "App validada (rollback OTA cancelado)");
    } else {
        ESP_LOGW(TAG, "mark_app_valid: %s", esp_err_to_name(err));
    }
    vTaskDelete(NULL);
}
#endif

void ota_boot_init(void)
{
#if CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE
    xTaskCreate(ota_validate_task, "ota_validate", 2048, NULL, 3, NULL);
#endif
}

/* ----------------------------------------------------------------
 * Handlers HTTP
 * ---------------------------------------------------------------- */
static esp_err_t ota_get_handler(httpd_req_t *req)
{
    const esp_app_desc_t *app = esp_app_get_description();
    char resp[128];
    snprintf(resp, sizeof(resp), "%s v%s - OTA: POST /ota (header X-OTA-Token)",
             app->project_name, app->version);
    httpd_resp_sendstr(req, resp);
    return ESP_OK;
}

static void ota_restart_cb(void *arg)
{
    esp_restart();
}

static esp_err_t ota_post_handler(httpd_req_t *req)
{
    /* 1. Validar token */
    char token[48] = {0};
    if (httpd_req_get_hdr_value_str(req, "X-OTA-Token", token, sizeof(token)) != ESP_OK ||
        strcmp(token, OTA_TOKEN) != 0) {
        ESP_LOGW(TAG, "OTA rechazado: token invalido o ausente");
        httpd_resp_send_err(req, HTTPD_401_UNAUTHORIZED, "Token invalido");
        return ESP_FAIL;
    }

    /* 2. Particion destino */
    const esp_partition_t *update_partition = esp_ota_get_next_update_partition(NULL);
    if (update_partition == NULL) {
        ESP_LOGE(TAG, "No hay particion OTA disponible");
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "Sin particion OTA");
        return ESP_FAIL;
    }

    ESP_LOGI(TAG, "OTA inicio -> %s @ 0x%lx (%d bytes)",
             update_partition->label, (unsigned long)update_partition->address,
             req->content_len);

    /* 3. Escritura */
    esp_ota_handle_t ota_handle;
    esp_err_t err = esp_ota_begin(update_partition, OTA_WITH_SEQUENTIAL_WRITES, &ota_handle);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "esp_ota_begin: %s", esp_err_to_name(err));
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "ota_begin fallo");
        return ESP_FAIL;
    }

    char *buf = malloc(OTA_BUF_SIZE);
    if (buf == NULL) {
        esp_ota_abort(ota_handle);
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "Sin memoria");
        return ESP_FAIL;
    }

    int remaining = req->content_len;
    while (remaining > 0) {
        int to_read = (remaining < OTA_BUF_SIZE) ? remaining : OTA_BUF_SIZE;
        int received = httpd_req_recv(req, buf, to_read);
        if (received < 0) {
            if (received == HTTPD_SOCK_ERR_TIMEOUT) {
                continue;   // reintentar en timeout de socket
            }
            ESP_LOGE(TAG, "Error recibiendo datos: %d", received);
            free(buf);
            esp_ota_abort(ota_handle);
            httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "Error de recepcion");
            return ESP_FAIL;
        }
        if (received == 0) {
            continue;
        }
        err = esp_ota_write(ota_handle, buf, received);
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "esp_ota_write: %s", esp_err_to_name(err));
            free(buf);
            esp_ota_abort(ota_handle);
            httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "ota_write fallo");
            return ESP_FAIL;
        }
        remaining -= received;
    }
    free(buf);

    /* 4. Validar imagen y marcar como boot */
    err = esp_ota_end(ota_handle);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "esp_ota_end: %s (imagen corrupta o invalida)", esp_err_to_name(err));
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "Imagen invalida");
        return ESP_FAIL;
    }

    err = esp_ota_set_boot_partition(update_partition);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "esp_ota_set_boot_partition: %s", esp_err_to_name(err));
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "set_boot fallo");
        return ESP_FAIL;
    }

    ESP_LOGI(TAG, "OTA OK -> %s, reiniciando...", update_partition->label);
    httpd_resp_sendstr(req, "OTA OK - reiniciando");

    /* Reinicio diferido para que la respuesta HTTP salga primero */
    const esp_timer_create_args_t targs = {
        .callback = ota_restart_cb,
        .name = "ota_restart",
    };
    esp_timer_handle_t restart_timer;
    esp_timer_create(&targs, &restart_timer);
    esp_timer_start_once(restart_timer, 1000 * 1000);
    return ESP_OK;
}

/* ----------------------------------------------------------------
 * Arranque del servidor (idempotente)
 * ---------------------------------------------------------------- */
esp_err_t ota_server_start(void)
{
    if (ota_httpd != NULL) {
        return ESP_OK;   // ya iniciado
    }

    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.max_uri_handlers = 4;
    config.recv_wait_timeout = 30;   // uploads grandes
    config.send_wait_timeout = 30;

    esp_err_t err = httpd_start(&ota_httpd, &config);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "httpd_start: %s", esp_err_to_name(err));
        return err;
    }

    const httpd_uri_t uri_root = {
        .uri = "/",
        .method = HTTP_GET,
        .handler = ota_get_handler,
    };
    const httpd_uri_t uri_ota = {
        .uri = "/ota",
        .method = HTTP_POST,
        .handler = ota_post_handler,
    };
    httpd_register_uri_handler(ota_httpd, &uri_root);
    httpd_register_uri_handler(ota_httpd, &uri_ota);

    ESP_LOGI(TAG, "Servidor OTA activo en puerto %d (POST /ota)", config.server_port);
    return ESP_OK;
}
