# MotoMami Ultimate

Sistema de infoentretenimiento para **Raspberry Pi Zero 2W** con pantallas duales ST7789 (GMT020-02). GPS, música, video, Android Auto, cámara en vivo y DOOM, controlado por botones GPIO o mando Xbox Bluetooth.

## Arquitectura

```
├── src/          # Código unificado (nuevo) - servicios concurrentes con SystemState
├── final/        # Código legacy - basado en procesos separados + fb_daemon
├── tools/        # Utilidades (prefetch de tiles OSM)
├── deploy/       # Instalación con systemd (arranque automático)
└── .agents/      # Reglas para asistentes de IA (opencode)
```

### Hardware

| Componente | Conexión |
|---|---|
| Pantalla #1 (Mapa) | CS=GPIO17, DC=GPIO27, RST=GPIO22 |
| Pantalla #2 (Datos) | CS=GPIO24, DC=GPIO25, RST=GPIO23 |
| GPS SIM7600-G | `/dev/ttyUSB2` (AT), `/dev/ttyUSB1` (NMEA) |
| Cámara | CSI (Picamera2) |
| Botones GPIO | Arriba=GPIO13, Abajo=GPIO26, Der=GPIO5, Izq=GPIO6, Enter=GPIO12, Atrás=GPIO16 |

## Inicio rápido

```bash
cp config.ini.example config.ini  # editar credenciales
sudo pip install -r final/src/requirements.txt
sudo python3 src/main.py
```

## Funcionalidades

- **GPS** con mapas OSM offline en pantalla dual
- **Telemetría** MQTT a ThingsBoard y broker local Mosquitto
- **Reproductor de video** vía ffmpeg
- **Reproductor de música** con pygame (fondo persistente)
- **Android Auto** (placeholder)
- **DOOM** con Chocolate Doom + Xvfb + captura mss
- **Cámara en vivo** con Picamera2
- **Control** por botones GPIO y mando Xbox Bluetooth

## Stack técnico

Python 3.x · Pillow · paho-mqtt · pyserial · pygame · psutil · ffmpeg · staticmap · adafruit-blinka

## Repositorios

- Actual: https://github.com/MarioAntizana1/Motomami-unificado
- Anterior: https://github.com/MarioAntizana1/motomami-raspberry
