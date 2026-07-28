/*
 * ota_server.h — Servidor HTTP OTA compartido (Motomami ESP32-C6)
 *
 * Endpoint: POST /ota con header "X-OTA-Token: motomami-ota-2026"
 *           Body  = binario .bin de la aplicacion
 *           GET / = info del modulo (project_name + version)
 *
 * Uso tipico:
 *   ota_boot_init();        // al inicio de app_main (auto-validacion anti-rollback)
 *   ota_server_start();     // cuando hay IP (idempotente, llamar en GOT_IP)
 */
#pragma once

#include "esp_err.h"

/* Programa la auto-validacion de la app (cancela rollback OTA a los 30 s).
 * Es no-op si la app no arranco en estado "pendiente de verificacion". */
void ota_boot_init(void);

/* Inicia el servidor HTTP OTA (puerto 80). Idempotente: si ya esta
 * iniciado devuelve ESP_OK sin hacer nada. */
esp_err_t ota_server_start(void);
