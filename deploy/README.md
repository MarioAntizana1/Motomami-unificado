# Deploy - Instalación con systemd

## Requisitos

- Raspberry Pi con RPi OS Lite (o cualquier variante)
- Python 3.14+, pip, dependencias instaladas
- Repositorio clonado en `/home/motomami/motomami-ultimate`
- `config.ini` configurado con tus credenciales

## Instalación

```bash
# 1. Copiar el archivo de servicio
sudo cp motomami.service /etc/systemd/system/

# 2. Recargar systemd
sudo systemctl daemon-reload

# 3. Habilitar para que arranque con el sistema
sudo systemctl enable motomami

# 4. Iniciar ahora (opcional, puedes reiniciar directamente)
sudo systemctl start motomami
```

## Comandos útiles

```bash
# Ver estado
sudo systemctl status motomami

# Ver logs en tiempo real
sudo journalctl -u motomami -f

# Ver logs completos
sudo journalctl -u motomami

# Reiniciar el servicio
sudo systemctl restart motomami

# Detener
sudo systemctl stop motomami

# Deshabilitar (no arranca con el sistema)
sudo systemctl disable motomami
```

## Notas

- Ejecuta como `root` para acceso a `/dev/fb*`, `/dev/ttyUSB*` y GPIO
- Si el proceso falla, systemd lo reinicia automáticamente a los 5 segundos
- Los logs se ven con `journalctl`, no se crean archivos de log separados
