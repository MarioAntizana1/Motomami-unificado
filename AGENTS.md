# MotoMami Ultimate - Reglas para Agentes de IA

## Stack

- Python 3.x, Raspberry Pi Zero 2W
- Pantallas: ST7789 SPI (240x320), framebuffer `/dev/fb1`, `/dev/fb2`
- GPS: SIM7600-G vía AT commands
- MQTT: ThingsBoard cloud + Mosquitto local
- Audio: pygame.mixer / ALSA / Fiio DAC
- Video: ffmpeg (frame extraction)
- Botones: GPIO 13, 26, 5, 6, 12, 16
- Mando: Xbox Bluetooth

## Estructura

- `src/` - código **unificado nuevo** (servicios con hilos, SystemState singleton)
- `final/` - código **legacy** (procesos separados con fork)
- `tools/` - utilidades auxiliares
- `config.ini.example` - plantilla de configuración (copiar a `config.ini`)

## Reglas

1. **No exponer credenciales** - `config.ini` y `.agents/rules/laconexion.md` están en `.gitignore`. Nunca hardcodear tokens.
2. **Modificar siempre `src/`** (unificado), no `final/` (legacy) a menos que se pida explícitamente.
3. **Ejecución con sudo** - requiere acceso a `/dev/fb*`, `/dev/ttyUSB*`, GPIO.
4. **Hot reload** - detener con Ctrl+C, los servicios hacen shutdown graceful.
5. **Python 3.14+** - usar sintaxis moderna, evitar compatibilidad hacia atrás innecesaria.

## Comandos frecuentes

```bash
sudo python3 src/main.py                     # Iniciar sistema unificado
sudo python3 final/src/main.py               # Iniciar sistema legacy
sudo python3 final/src/tests/test_gmt020_dual.py  # Test pantallas
```

## Workflow

1. Leer `Objetivos.md` en `.agents/rules/` para conocer bugs/features pendientes
2. Para cambios en GPIO/pinout, revisar `pinout-rpi.md`
3. Verificar con test de pantalla dual antes de deploy
4. Commit solo cuando se solicite explícitamente
