# MotoMami Ultimate - Reglas para Agentes de IA

## Stack

- Python 3.x, Raspberry Pi Zero 2W
- Pantallas: ST7789 SPI (240x320), framebuffer `/dev/fb1` (inferior), `/dev/fb2` (superior) — apiladas verticalmente
  - El canvas 640x240 mapea: izquierda (x:0-319) → fb1 (abajo), derecha (x:320-639) → fb2 (arriba)
- GPS: SIM7600-G vía AT commands
- MQTT: ThingsBoard cloud + Mosquitto local
- Audio: pygame.mixer / ALSA / Fiio DAC
- Video: ffmpeg (frame extraction)
- Botones: GPIO 13 (UP), 26 (DOWN), 5 (RIGHT), 6 (LEFT), 12 (ENTER), 16 (BACK)
- Mando: Xbox Bluetooth (mapeado a UP/DOWN/LEFT/RIGHT/ENTER/BACK via InputManager)
- **Sin teclado** — todas las interacciones deben funcionar solo con botones GPIO y mando Xbox (UP/DOWN/ENTER/BACK)

## Estructura

- `src/` - código **unificado nuevo** (servicios con hilos, SystemState singleton)
- `final/` - código **legacy** (procesos separados con fork)
- `tools/` - utilidades auxiliares
- `config.ini.example` - plantilla de configuración (copiar a `config.ini`)
- `deploy/` - archivos para instalación (systemd service, instrucciones)

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

# systemd (arranque automático)
sudo systemctl start motomami                # Iniciar servicio
sudo systemctl enable motomami               # Habilitar en boot
sudo journalctl -u motomami -f               # Ver logs
```

## Workflow

1. **Leer `memory.md`** en `.agents/rules/` para cargar contexto entre sesiones
2. Leer `Objetivos.md` en `.agents/rules/` para conocer bugs/features pendientes
3. Para cambios en GPIO/pinout, revisar `pinout-rpi.md`
4. **Actualizar `memory.md`** al final de cada sesión con bugs corregidos, decisiones y aprendizajes
5. Verificar con test de pantalla dual antes de deploy

## Deploy automático

Después de cada cambio en `src/` (o cualquier modificación que afecte al sistema en ejecución):

1. **Commit + Push** a GitHub (`main`)
2. **Actualizar RPi** — descargar archivos desde raw.githubusercontent.com
3. **Actualizar Graphify** — `graphify update .` (sin costo de API)
4. **Reiniciar servicio** — `ssh-rpi_sudo-exec "systemctl restart motomami"`


