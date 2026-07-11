"""
gps_service.py - Servicio GPS siempre activo con caché de última posición.
Lee del SIM7600 y actualiza SystemState.gps continuamente.
"""
import threading
import time
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config_loader import GPS_AT_PORT, GPS_BAUD

# Intentar importar el driver real; si no, usar stub
_DRIVERS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "drivers")
if _DRIVERS not in sys.path:
    sys.path.insert(0, _DRIVERS)

try:
    from sim7600_gps import SIM7600GPS
    _HAS_DRIVER = True
except ImportError:
    _HAS_DRIVER = False
    print("[GPSService] Driver SIM7600 no disponible")


class GPSService(threading.Thread):
    """
    Hilo daemon que lee GPS continuamente y actualiza SystemState.
    Garantiza que la última posición conocida siempre esté disponible
    (incluso si se pierde el fix o se desconecta el módulo).
    """

    def __init__(self, state=None):
        super().__init__(name="GPSService", daemon=True)
        self._state = state
        self._stop_event = threading.Event()
        self._gps = None
        self._connected = False

    def run(self):
        print(f"[GPSService] Iniciando en {GPS_AT_PORT}")
        if not _HAS_DRIVER:
            print("[GPSService] Sin driver, usando datos simulados.")
            self._run_stub()
            return

        while not self._stop_event.is_set():
            try:
                self._connect_and_read()
            except Exception as e:
                print(f"[GPSService] Error: {e}. Reintentando en 10s...")
                self._stop_event.wait(timeout=10)

    def _connect_and_read(self):
        """Conecta al SIM7600 y lee datos en loop."""
        if not os.path.exists(GPS_AT_PORT):
            print(f"[GPSService] Puerto {GPS_AT_PORT} no disponible. Esperando...")
            self._stop_event.wait(timeout=5)
            return

        print(f"[GPSService] Conectando a {GPS_AT_PORT}...")
        self._gps = SIM7600GPS(at_port=GPS_AT_PORT, baudrate=GPS_BAUD, auto_start=True)
        self._gps.set_callback(self._on_gps_data)
        self._connected = True
        print("[GPSService] GPS activo. Esperando fix...")

        # Esperar hasta que se pida detener
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=1)

    def _on_gps_data(self, data):
        """Callback del driver GPS. Actualiza SystemState."""
        if self._state:
            self._state.update_gps(data)

    def _run_stub(self):
        """Datos simulados cuando no hay driver (para testing)."""
        import math
        t = 0
        while not self._stop_event.is_set():
            # Simular una ruta circular pequeña
            class FakeData:
                has_fix = True
                altitude = 2800.0
                speed_kmh = 60.0
                track_angle = (t * 5) % 360
                num_satellites = 8
                time = "120000"
                date = "090726"
                def get_coordinates_decimal(self):
                    lat = -0.2295 + 0.001 * math.sin(math.radians(t * 3))
                    lon = -78.5249 + 0.001 * math.cos(math.radians(t * 3))
                    return lat, lon

            if self._state:
                self._state.update_gps(FakeData())
            t += 1
            self._stop_event.wait(timeout=2)

    def stop(self):
        print("[GPSService] Deteniendo...")
        self._stop_event.set()
        if self._gps:
            try:
                self._gps.stop()
            except Exception:
                pass
        self._connected = False
        print("[GPSService] Detenido.")

    @property
    def is_connected(self) -> bool:
        return self._connected
