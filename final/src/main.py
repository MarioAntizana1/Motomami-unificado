"""
main.py - Lanzador principal de MotoMami
=========================================
Bucle:
  1. Ejecuta main_menu.py (interfaz grafica con pantallas)
  2. main_menu.py se CIERRA al seleccionar app (escribe flag)
  3. main.py lee el flag y lanza la app seleccionada
  4. App termina -> vuelta al paso 1

Asi CERO conflictos de GPIO: cada proceso toma el hardware completo.
"""

import os
import sys
import subprocess
import time

FLAG_FILE = "/tmp/motomami_next_app.txt"


def main():
    print("=" * 50)
    print("  MotoMami - Sistema Principal")
    print("=" * 50)

    # Limpiar flag
    if os.path.exists(FLAG_FILE):
        os.remove(FLAG_FILE)

    # Lanzar daemon GPS en background (no se cierra nunca)
    daemon = subprocess.Popen(
        ["sudo", "python3", os.path.join(os.path.dirname(__file__), "apps", "gps_daemon.py")],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    print("[Main] Daemon GPS iniciado en background (PID=%d)" % daemon.pid)

    while True:
        # --- MENU GRAFICO ---
        print("\n[Main] Lanzando menu...")
        proc = subprocess.Popen(
            ["sudo", "python3", os.path.join(os.path.dirname(__file__), "apps", "main_menu.py")]
        )
        proc.wait()

        # --- LEER FLAG ---
        if not os.path.exists(FLAG_FILE):
            print("[Main] Menu cerrado sin seleccionar app. Saliendo del sistema.")
            break

        with open(FLAG_FILE, 'r') as f:
            cmd_line = f.read().strip()
        os.remove(FLAG_FILE)

        if cmd_line == "EXIT":
            print("[Main] Salir seleccionado. Apagando sistema.")
            break

        print(f"[Main] Ejecutando: {cmd_line}")

        # --- EJECUTAR APP ---
        parts = cmd_line.split()
        app = subprocess.Popen(parts)
        app.wait()

        print(f"\n[Main] App finalizada (codigo={app.returncode}). Volviendo al menu...")
        time.sleep(1)

    # --- LIMPIEZA FINAL ---
    print("[Main] Deteniendo daemon GPS...")
    daemon.terminate()
    try:
        daemon.wait(timeout=5)
    except subprocess.TimeoutExpired:
        daemon.kill()
    print("[Main] Apagado limpio.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[Main] Interrumpido.")
