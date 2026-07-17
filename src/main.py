#!/usr/bin/env python3
"""
main.py - Entry point de MotoMami Unificado
Maneja la inicialización de los servicios core (Estado, Entradas, Telemetría)
e invoca el menú principal que dirige a las demás aplicaciones.
"""

import sys
import os
import time
import threading
import signal

_SRC = os.path.dirname(os.path.abspath(__file__))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import config_loader
from core.state import SystemState
from core.input_manager import InputManager
from core.gps_service import GPSService
from core.telemetria_service import TelemetriaService
from core.music_service import MusicService
from apps.main_menu import MainMenu
from apps.gps_display_app import GPSDisplayApp
from apps.video_player_app import VideoPlayerApp
from apps.android_auto_app import AndroidAutoApp
from apps.gps_diag_app import GPSDiagApp
from apps.connections_app import ConnectionsApp
from apps.bluetooth_manager_app import BluetoothManagerApp

class MotoMamiSystem:
    def __init__(self):
        self.state = SystemState()
        self.input_mgr = InputManager()
        
        # Servicios
        self.gps_svc = GPSService(self.state)
        self.telemetria_svc = TelemetriaService(self.state)
        self.music_svc = MusicService(self.state)
        
        self.running = False
        
        # Para graceful shutdown
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    def _handle_signal(self, sig, frame):
        print(f"\n[Main] Recibida señal {sig}. Apagando sistema...")
        self.shutdown()
        sys.exit(0)

    def start_services(self):
        print("[Main] Iniciando Input Manager...")
        self.input_mgr.start()
        
        print("[Main] Iniciando GPS Service...")
        self.gps_svc.start()
        
        print("[Main] Iniciando Telemetria Service...")
        self.telemetria_svc.start()
        
        print("[Main] Iniciando Music Service...")
        self.music_svc.init()
        
        # El SystemState (recursos del sistema) ya inicia automáticamente su hilo interno
        self.running = True

    def shutdown(self):
        self.running = False
        print("[Main] Deteniendo servicios...")
        self.music_svc.quit()
        self.telemetria_svc.stop()
        self.gps_svc.stop()
        self.input_mgr.stop()
        print("[Main] Sistema detenido de forma segura.")

    def run(self):
        self.start_services()
        
        try:
            while self.running:
                menu = MainMenu(self.input_mgr, self.state)
                print("[Main] Lanzando UI principal...")
                app_key = menu.run()
                
                if app_key == "gps":
                    print("[Main] Lanzando GPS App")
                    app = GPSDisplayApp(self.input_mgr, self.state)
                    app.run()
                elif app_key == "video":
                    print("[Main] Lanzando Video Player App")
                    app = VideoPlayerApp(self.input_mgr, self.state)
                    app.run()
                elif app_key == "android_auto" or app_key == "camera":
                    # Mapeando cámara o android_auto a la app placeholder
                    print("[Main] Lanzando Android Auto App (Placeholder)")
                    app = AndroidAutoApp(self.input_mgr, self.state)
                    app.run()
                elif app_key == "music":
                    print("[Main] Lanzando Music Player App")
                    from apps.music_player_app import MusicPlayerApp
                    app = MusicPlayerApp(self.input_mgr, self.state, self.music_svc)
                    app.run()
                elif app_key == "doom":
                    print("[Main] Lanzando Doom App")
                    from apps.doom_app import DoomApp
                    app = DoomApp(self.input_mgr, self.state)
                    app.run()
                elif app_key == "gps_diag":
                    print("[Main] Lanzando GPS Diagnostico")
                    app = GPSDiagApp(self.input_mgr, self.state)
                    app.run()
                elif app_key == "conex":
                    print("[Main] Lanzando Conexiones")
                    app = ConnectionsApp(self.input_mgr, self.state)
                    app.run()
                elif app_key == "bt_mgr":
                    print("[Main] Lanzando Bluetooth Manager")
                    app = BluetoothManagerApp(self.input_mgr, self.state)
                    app.run()
                elif app_key == "telem":
                    # Si tuvieras una app para visualizar la telemetría, se lanzaría aquí.
                    print("[Main] App de telemetría no tiene interfaz gráfica actualmente.")
                    time.sleep(1)
                elif app_key == "exit":
                    print("[Main] Saliendo...")
                    break
        except Exception as e:
            print(f"[Main] Error fatal en la UI: {e}")
        finally:
            self.shutdown()


if __name__ == "__main__":
    print("========================================")
    print("      MOTOMAMI OS - Iniciando...        ")
    print("========================================")
    
    app = MotoMamiSystem()
    app.run()
