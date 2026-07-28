# Proyecto: Motomami Velocímetro/Temperatura ESP32-C6

## Hardware
- **MCU**: ESP32-C6 (Seeed Xiao ESP32-C6)
- **Sensor velocidad**: GPIO21 (pulsos de sensor de efecto Hall)
- **Conexión**: USB

## Software
- **Framework**: ESP-IDF vía PlatformIO
- **Build**: `pio run`
- **Flash**: `pio run --target upload`
- **Monitor**: `pio device monitor`

## Funcionamiento
- Lee pulsos del sensor de velocidad (GPIO21) con interrupción por flanco
- Calcula velocidad (km/h) y distancia (km) en base a:
  - 3 pulsos por revolución
  - Diámetro de rueda: 43.0 cm
- Publica datos vía MQTT al broker local (`192.168.42.1`)
- Tópicos: `motomami/velocimetro/data`, `motomami/velocimetro/odometro`, `motomami/velocimetro/status`
- Odómetro persistente en NVS (guarda cada 250 pulsos y al detectar detención)
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
