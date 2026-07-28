# Proyecto: Motomami Input ESP32-C6

## Hardware
- **MCU**: ESP32-C6 (Seeed Xiao ESP32-C6)
- **Entradas**: 5× optoacopladas (GPIO18, 2, 21, 22, 23)
- **Conexión**: USB

## Software
- **Framework**: ESP-IDF vía PlatformIO
- **Build**: `pio run`
- **Flash**: `pio run --target upload`
- **Monitor**: `pio device monitor`

## Funcionamiento
- Lee 5 entradas digitales con debounce por software
- Publica cambios vía MQTT al broker local (`192.168.42.1`)
- Tópicos: `motomami/intermitente_izquierda`, `motomami/intermitente_derecha`, `motomami/intermitente_emergencia`, `motomami/frenado`, `motomami/luz_nocturna`
- Reporta estado online/offline, IP y RSSI periódicamente
- WiFi: `Motomami-net`

## Estructura
```
src/
  main.c              # Código principal
  CMakeLists.txt      # Build config
components/
  esp_mqtt/           # Componente MQTT (ESP-IDF)
platformio.ini        # Config PlatformIO
```
