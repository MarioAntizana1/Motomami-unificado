#!/bin/bash
# install_fb.sh - Instala el daemon de framebuffer en la Raspberry Pi
# ==================================================================
# Copia archivos, crea servicio systemd, instala dependencias.
#
# Uso:  bash install_fb.sh
#       (ejecutar en la Pi, NO en Windows)

set -e

PI_USER="motomami"
PI_HOME="/home/${PI_USER}"
FINAL_DIR="${PI_HOME}/final"

echo "============================================"
echo "  MotoMami - Instalador FB Daemon"
echo "============================================"

# Verificar que estamos en la Pi
if ! grep -q "Raspberry" /proc/device-tree/model 2>/dev/null; then
    echo "ADVERTENCIA: No parece ser una Raspberry Pi."
    echo "Este script debe ejecutarse EN la Raspberry Pi."
    echo "Continua bajo tu propio riesgo..."
fi

# 1. Dependencias Python
echo ""
echo "[1/5] Instalando dependencias Python..."
sudo pip3 install numpy Pillow 2>/dev/null || pip3 install numpy Pillow

# 2. Verificar archivos necesarios
echo ""
echo "[2/5] Verificando archivos fuente..."
REQUIRED=(
    "${FINAL_DIR}/src/fb_daemon.py"
    "${FINAL_DIR}/src/lib/fb_display.py"
    "${FINAL_DIR}/src/drivers/st7789_improved.py"
)
for f in "${REQUIRED[@]}"; do
    if [ ! -f "$f" ]; then
        echo "ERROR: Falta $f"
        echo "Ejecuta primero upload_and_verify.py desde Windows para sincronizar."
        exit 1
    fi
done
echo "   Todos los archivos presentes."

# 3. Crear servicio systemd
echo ""
echo "[3/5] Creando servicio systemd..."

sudo tee /etc/systemd/system/motomami-fb.service > /dev/null << 'SERVICEOF'
[Unit]
Description=MotoMami Framebuffer Daemon (ST7789 Dual Display)
After=multi-user.target
Wants=multi-user.target

[Service]
Type=simple
User=root
WorkingDirectory=/home/motomami/final/src
ExecStart=/usr/bin/python3 /home/motomami/final/src/fb_daemon.py
Restart=always
RestartSec=3
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SERVICEOF

echo "   Servicio creado: /etc/systemd/system/motomami-fb.service"

# 4. Habilitar y arrancar
echo ""
echo "[4/5] Habilitando y arrancando servicio..."

# Detener si ya estaba corriendo
sudo systemctl stop motomami-fb 2>/dev/null || true

sudo systemctl daemon-reload
sudo systemctl enable motomami-fb
sudo systemctl start motomami-fb

sleep 3

# 5. Verificar
echo ""
echo "[5/5] Verificando..."

if sudo systemctl is-active --quiet motomami-fb; then
    echo "   SERVICIO ACTIVO"
    sudo systemctl status motomami-fb --no-pager -l | head -15
else
    echo "   ERROR: El servicio no arranco."
    echo "   Logs:"
    sudo journalctl -u motomami-fb --no-pager -n 20
    exit 1
fi

# Verificar socket
if [ -S /tmp/motomami_fb.sock ]; then
    echo ""
    echo "   Socket listo: /tmp/motomami_fb.sock"
    ls -la /tmp/motomami_fb.sock
else
    echo "   ADVERTENCIA: Socket no encontrado."
fi

echo ""
echo "============================================"
echo "  INSTALACION COMPLETA"
echo "============================================"
echo ""
echo "Comandos utiles:"
echo "  Ver estado:   sudo systemctl status motomami-fb"
echo "  Ver logs:     sudo journalctl -u motomami-fb -f"
echo "  Reiniciar:    sudo systemctl restart motomami-fb"
echo "  Detener:      sudo systemctl stop motomami-fb"
echo ""
echo "Ahora las apps pueden usar 'from fb_display import FbDisplay'"
echo "sin necesidad de tocar SPI directamente."
