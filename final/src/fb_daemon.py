#!/usr/bin/env python3
"""
fb_daemon.py - FRAMEBUFFER DAEMON para MotoMami
================================================
Servicio permanente que posee el bus SPI y maneja AMBAS pantallas ST7789.

Expone un socket Unix (/tmp/motomami_fb.sock) donde las apps mandan frames
RGB565 sin necesidad de tocar SPI directamente.

Protocolo (binario):
  [4 bytes LE: display_id] [payload RGB565]

  display_id:
    0 = Heartbeat/ping (responde "OK\n", sin payload)
    1 = Display #1 (320x240 RGB565 = 153,600 bytes)
    2 = Display #2 (320x240 RGB565 = 153,600 bytes)
    3 = AMBAS pantallas (640x240 RGB565 = 307,200 bytes, se parte en dos)

Ejecutar como servicio systemd:
  sudo python3 /home/motomami/final/src/fb_daemon.py
"""

import os
import sys
import time
import socket
import struct
import glob
import signal
import threading

# ── Asegurar rutas ──
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_BASE_DIR = os.path.dirname(_THIS_DIR)
for _p in [os.path.join(_THIS_DIR, 'drivers'),
           os.path.join(_BASE_DIR, 'drivers')]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import board
import busio
import digitalio
from st7789_improved import ST7789

SOCKET_PATH = "/tmp/motomami_fb.sock"
PID_FILE = "/tmp/motomami_fb.pid"

# Display configs (matching vp_display.py)
DISPLAYS = {
    1: {'cs': 17, 'dc': 27, 'rst': 22},
    2: {'cs': 24, 'dc': 25, 'rst': 23},
}

W, H = 240, 320        # Physical
ROTATION = 1            # Landscape → 320x240 effective
FRAME_SIZE = (H * W * 2)  # 320 * 240 * 2 = 153,600 bytes per frame
BOTH_SIZE = FRAME_SIZE * 2  # 307,200 bytes


class FbDaemon:
    def __init__(self):
        self.spi = None
        self.displays = {}
        self._disp_pins = []
        self.running = True
        self.server = None
        self._lock = threading.Lock()

        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

    def _handle_signal(self, signum, frame):
        print(f"[Daemon] Signal {signum} recibida, apagando...")
        self.running = False

    def _clean_stale_fifos(self):
        for lgd in glob.glob('/home/motomami/**/.lgd-nfy*', recursive=True):
            try:
                os.remove(lgd)
            except:
                pass
        for lgd in glob.glob('/tmp/.lgd-nfy*'):
            try:
                os.remove(lgd)
            except:
                pass

    def init_hardware(self):
        """Inicializa ambas pantallas ST7789 via SPI."""
        print("[Daemon] Inicializando hardware de displays...")
        self._clean_stale_fifos()

        self.spi = busio.SPI(clock=board.SCK, MOSI=board.MOSI)

        for disp_id, pins in DISPLAYS.items():
            try:
                cs = digitalio.DigitalInOut(getattr(board, f'D{pins["cs"]}'))
                dc = digitalio.DigitalInOut(getattr(board, f'D{pins["dc"]}'))
                rst = digitalio.DigitalInOut(getattr(board, f'D{pins["rst"]}'))
                self._disp_pins.extend([cs, dc, rst])

                disp = ST7789(
                    self.spi, cs, dc, rst,
                    width=W, height=H, rotation=ROTATION,
                    baudrate=40000000,
                    bgr=False, invert=True,
                )
                disp.fill((0, 0, 0))
                self.displays[disp_id] = disp
                print(f"[Daemon] Display #{disp_id} listo ({disp.width}x{disp.height}) "
                      f"CS=GPIO{pins['cs']}")
            except Exception as e:
                print(f"[Daemon] Display #{disp_id} NO DISPONIBLE: {e}")

        if not self.displays:
            print("[Daemon] ERROR: Ninguna pantalla disponible. Abortando.")
            return False

        return True

    def release_hardware(self):
        print("[Daemon] Liberando hardware...")
        for disp in self.displays.values():
            try:
                disp.fill((0, 0, 0))
            except:
                pass
        for p in self._disp_pins:
            try:
                p.deinit()
            except:
                pass
        self._disp_pins = []
        try:
            self.spi.deinit()
        except:
            pass
        self.spi = None
        self.displays = {}

    def push_frame(self, display_id, data):
        """Empuja un frame RGB565 a un display especifico."""
        with self._lock:
            if display_id == 3:
                # BOTH: split 640x240 into two 320x240 frames
                if len(data) != BOTH_SIZE:
                    print(f"[Daemon] BOTH frame size mismatch: {len(data)} != {BOTH_SIZE}")
                    return False
                left = data[:FRAME_SIZE]
                right = data[FRAME_SIZE:]
                ok = True
                if 1 in self.displays:
                    self.displays[1].display_raw(left)
                else:
                    ok = False
                if 2 in self.displays:
                    self.displays[2].display_raw(right)
                else:
                    ok = False
                return ok
            else:
                if display_id not in self.displays:
                    return False
                if len(data) != FRAME_SIZE:
                    print(f"[Daemon] Display #{display_id} frame size mismatch: {len(data)} != {FRAME_SIZE}")
                    return False
                self.displays[display_id].display_raw(data)
                return True

    def start_server(self):
        """Inicia el servidor Unix socket."""
        # Limpiar socket viejo
        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)

        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(SOCKET_PATH)
        os.chmod(SOCKET_PATH, 0o666)  # Accesible para cualquier usuario
        self.server.listen(5)
        self.server.settimeout(1.0)  # Para poder verificar self.running
        print(f"[Daemon] Escuchando en {SOCKET_PATH}")

    def _handle_client(self, conn):
        """Maneja una conexion de cliente."""
        try:
            while self.running:
                # Leer header: 4 bytes (display_id como uint32 LE)
                header = self._recv_exact(conn, 4)
                if header is None:
                    break

                display_id = struct.unpack('<I', header)[0]

                if display_id == 0:
                    # Heartbeat / ping
                    conn.sendall(b"OK\n")
                    continue

                # Leer payload
                expected = BOTH_SIZE if display_id == 3 else FRAME_SIZE
                data = self._recv_exact(conn, expected)
                if data is None:
                    break

                self.push_frame(display_id, data)

                # ACK
                conn.sendall(b"OK\n")
        except Exception as e:
            print(f"[Daemon] Error cliente: {e}")
        finally:
            try:
                conn.close()
            except:
                pass

    def _recv_exact(self, conn, n):
        """Recibe exactamente n bytes."""
        buf = b''
        while len(buf) < n:
            try:
                chunk = conn.recv(n - len(buf))
                if not chunk:
                    return None
                buf += chunk
            except socket.timeout:
                if not self.running:
                    return None
                continue
        return buf

    def run(self):
        if not self.init_hardware():
            print("[Daemon] Fallo inicializacion. Saliendo.")
            return 1

        self.start_server()

        print("[Daemon] Servicio listo. Aceptando conexiones...")

        while self.running:
            try:
                conn, addr = self.server.accept()
                # Manejar cada cliente en un hilo separado
                t = threading.Thread(target=self._handle_client, args=(conn,), daemon=True)
                t.start()
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    print(f"[Daemon] Error accept: {e}")

        # Cleanup
        print("[Daemon] Cerrando...")
        self.release_hardware()
        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)
        print("[Daemon] Adios!")
        return 0


if __name__ == '__main__':
    daemon = FbDaemon()
    sys.exit(daemon.run())
