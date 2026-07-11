# App MotoMami — Raspberry Pi Zero 2W

## Estructura del proyecto

```
src/
├── drivers/                    # Drivers de hardware
│   ├── st7789_improved.py     # Driver ST7789 para GMT020-02 (2 pantallas)
│   ├── sim7600_gps.py         # Control GPS del SIM7600-G por AT commands
│   └── camera.py              # Control cámara Picamera2
│
├── apps/                       # Aplicaciones
│   ├── main_menu.py           # Menú universal (botones físicos + mando Xbox)
│   ├── gps_display_app.py     # GPS + mapa + 2 pantallas
│   ├── camera_live.py         # Cámara en vivo en ST7789
│   ├── video_player.py        # Reproductor de video (ffmpeg + ST7789)
│   ├── doom_launcher.py       # Lanzador Chocolate Doom en ST7789
│   └── main.py                # Servidor web de cámara (Flask)
│
├── lib/                        # Librerías auxiliares
│   ├── map_renderer.py        # Renderizado de mapas OSM
│   ├── telemetria.py          # Publicación MQTT a ThingsBoard
│   ├── gps_parser.py          # Parser NMEA alternativo
│   └── config.py              # Configuración centralizada
│
├── video_player/               # Módulos del reproductor de video
│   ├── vp_config.py           # Configuración
│   ├── vp_audio.py            # Audio DAC Fiio
│   ├── vp_browser.py          # Navegador de archivos
│   ├── vp_controller.py       # Mando Xbox Bluetooth
│   ├── vp_display.py          # Pantallas duales (DisplayST7789 + DualDisplay)
│   └── vp_player.py           # Reproductor ffmpeg
│
├── tests/                      # Pruebas
│   └── test_gmt020_dual.py    # Test oficial de 2 pantallas ST7789
│
└── README.md                  # Este archivo
```

## Hardware

| Componente | Conexión |
|-----------|----------|
| Pantalla #1 (Mapa) | CS=GPIO17, DC=GPIO27, RST=GPIO22 |
| Pantalla #2 (Datos) | CS=GPIO24, DC=GPIO25, RST=GPIO23 |
| GPS SIM7600-G | /dev/ttyUSB2 (AT), /dev/ttyUSB1 (NMEA) |
| Cámara | CSI (Picamera2) |
| Botón Arriba | GPIO13 |
| Botón Abajo | GPIO26 |
| Botón Derecha | GPIO5 |
| Botón Izquierda | GPIO6 |
| Botón Enter | GPIO12 |
| Botón Atrás | GPIO16 |

## Uso

```bash
# Menú principal
sudo python3 apps/main_menu.py

# GPS + Mapas (directo)
sudo python3 apps/gps_display_app.py

# Cámara en vivo
sudo python3 apps/camera_live.py

# Reproductor de video
sudo python3 apps/video_player.py

# Test de pantallas
sudo python3 tests/test_gmt020_dual.py
```
