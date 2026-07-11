#!/usr/bin/env python3
"""camera_live.py

Vista en tiempo real de la camara en pantalla ST7789 (framebuffer nativo).
Optimizado para maximo rendimiento en Raspberry Pi Zero 2W.

Pipeline:
  Picamera2 (320x240 RGB) → PIL Image → /dev/fb1 (mmap) → ST7789

Solo usa Display #1 (/dev/fb1).

Uso:
  sudo python3 apps/camera_live.py
  sudo python3 apps/camera_live.py --fps 30
  sudo python3 apps/camera_live.py --hflip --vflip
"""

import time
import sys
import os

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_BASE_DIR = os.path.dirname(_THIS_DIR)
for _p in [os.path.join(_BASE_DIR, 'lib')]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import argparse
from PIL import Image

import board
import digitalio
from picamera2 import Picamera2
from fb_display import FramebufferDisplay

LANDSCAPE_W = 320
LANDSCAPE_H = 240


def parse_args():
    parser = argparse.ArgumentParser(
        description='Vista en vivo de la camara en pantalla ST7789 (FB Edition)'
    )
    parser.add_argument('--fps', type=int, default=30, help='FPS objetivo (default: 30)')
    parser.add_argument('--hflip', action='store_true', help='Voltear horizontalmente')
    parser.add_argument('--vflip', action='store_true', help='Voltear verticalmente')
    parser.add_argument('--show-fps', action='store_true', default=True)
    parser.add_argument('--no-show-fps', action='store_false', dest='show_fps')
    return parser.parse_args()


def main():
    args = parse_args()

    print("=" * 45)
    print("  Camara en Vivo - FB Edition")
    print("=" * 45)

    disp_w, disp_h = LANDSCAPE_W, LANDSCAPE_H

    # ── Abrir framebuffer nativo (Display #1 = /dev/fb1) ──
    print("[1/3] Abriendo framebuffer nativo /dev/fb1...")
    fb = None
    try:
        fb = FramebufferDisplay("/dev/fb1")
        print(f"      -> OK ({fb.width}x{fb.height})")
    except Exception as e:
        print(f"      -> /dev/fb1 NO disponible: {e}")
        fb = None

    # ── Inicializar camara ──
    print("[2/3] Inicializando camara (Picamera2)...")
    print(f"      Resolucion: {disp_w} x {disp_h}")

    try:
        picam2 = Picamera2(camera_num=0)
    except Exception as e:
        print(f"      -> ERROR: No se detecto camara CSI: {e}")
        return 1

    cam_config = picam2.create_video_configuration(
        main={"size": (disp_w, disp_h), "format": "RGB888"}
    )

    if args.hflip:
        picam2.horizontal_flip = True
    if args.vflip:
        picam2.vertical_flip = True

    picam2.configure(cam_config)
    picam2.start()

    frame_time = int(1_000_000 / args.fps)
    try:
        picam2.set_controls({"FrameDurationLimits": (frame_time, frame_time)})
    except Exception as e:
        print(f"      [Aviso] No se pudo fijar FrameDurationLimits: {e}")

    print("      Esperando estabilizacion (1s)...")
    time.sleep(1)
    print("      → Camara lista")

    # ── Loop principal ──
    print("[3/3] Iniciando vista en vivo...")
    print("      Ctrl+C para salir")

    frame_count = 0
    fps_actual = 0.0
    t_start = time.monotonic()
    t_fps_report = t_start
    expected_buf_size = disp_w * disp_h * 2

    try:
        btn_back = digitalio.DigitalInOut(board.D16)
        btn_back.direction = digitalio.Direction.INPUT
        btn_back.pull = digitalio.Pull.DOWN
    except Exception:
        btn_back = None

    try:
        while True:
            if btn_back and btn_back.value:
                print("\n→ Saliendo por boton fisico...")
                break

            frame = picam2.capture_array("main")  # numpy RGB888 (H,W,3)

            if fb:
                try:
                    img = Image.fromarray(frame, mode="RGB")
                    fb.show(img)
                except Exception as e:
                    print(f"\n→ Error escribiendo a /dev/fb1: {e}")
                    try:
                        fb.close()
                    except Exception:
                        pass
                    try:
                        fb = FramebufferDisplay("/dev/fb1")
                    except Exception:
                        fb = None

            frame_count += 1

            if args.show_fps:
                t_now = time.monotonic()
                elapsed = t_now - t_fps_report
                if elapsed >= 1.0:
                    fps_actual = frame_count / elapsed
                    frame_count = 0
                    t_fps_report = t_now
                    total_time = t_now - t_start
                    throughput_mbps = (fps_actual * expected_buf_size * 8) / 1e6
                    sys.stdout.write(
                        f"\r  FPS: {fps_actual:5.1f}  |  "
                        f"Tiempo: {total_time:6.0f}s  |  "
                        f"FB: {throughput_mbps:5.1f} Mbps  "
                    )
                    sys.stdout.flush()

    except KeyboardInterrupt:
        t_total = time.monotonic() - t_start
        print(f"\n\n→ Detenido despues de {t_total:.1f} segundos")
        print(f"  FPS promedio: {fps_actual:.1f}")

    finally:
        print("→ Limpiando recursos...")
        try:
            picam2.stop()
            picam2.close()
            print("  ✓ Camara cerrada")
        except Exception:
            pass
        if fb:
            try:
                fb.close()
                print("  ✓ Framebuffer cerrado")
            except:
                pass
        print("→ Listo")


if __name__ == "__main__":
    main()
