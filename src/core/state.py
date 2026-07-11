"""
state.py - Estado global compartido entre todos los hilos.
Thread-safe mediante threading.Lock y threading.Event.
"""
import threading
import time
from dataclasses import dataclass, field
from typing import Optional, Tuple, List


@dataclass
class GPSState:
    """Última posición GPS conocida (con caché)."""
    has_fix: bool = False
    lat: float = 0.0
    lon: float = 0.0
    altitude: float = 0.0
    speed_kmh: float = 0.0
    track_angle: float = 0.0
    num_satellites: int = 0
    gps_time: str = ""
    gps_date: str = ""
    last_update: float = 0.0

    # Caché: última posición válida conocida (nunca se borra)
    cached_lat: float = 0.0
    cached_lon: float = 0.0
    cached_has_fix: bool = False

    def update_from_driver(self, data):
        """Actualiza desde datos del driver SIM7600."""
        try:
            lat, lon = data.get_coordinates_decimal()
        except Exception:
            lat, lon = 0.0, 0.0

        self.has_fix = bool(data.has_fix)
        self.lat = lat
        self.lon = lon
        self.altitude = float(data.altitude or 0)
        self.speed_kmh = float(data.speed_kmh or 0)
        self.track_angle = float(data.track_angle or 0)
        self.num_satellites = int(data.num_satellites or 0)
        self.gps_time = str(data.time or "")
        self.gps_date = str(data.date or "")
        self.last_update = time.time()

        # Actualizar caché solo si hay fix válido
        if self.has_fix and lat != 0.0 and lon != 0.0:
            self.cached_lat = lat
            self.cached_lon = lon
            self.cached_has_fix = True

    def get_display_coords(self) -> Tuple[float, float]:
        """
        Retorna coordenadas para mostrar en pantalla.
        Si hay fix: posición actual.
        Si no hay fix: última posición conocida (caché).
        """
        if self.has_fix and self.lat != 0.0:
            return self.lat, self.lon
        if self.cached_has_fix:
            return self.cached_lat, self.cached_lon
        return 0.0, 0.0

    def is_stale(self, max_age_s: float = 10.0) -> bool:
        """True si los datos tienen más de max_age_s segundos."""
        return (time.time() - self.last_update) > max_age_s


@dataclass
class SystemMetrics:
    """Métricas del sistema (CPU, RAM, temp, etc.)."""
    cpu_percent: float = 0.0
    ram_percent: float = 0.0
    disk_percent: float = 0.0
    cpu_temp: float = 0.0
    uptime: float = 0.0
    last_update: float = 0.0


@dataclass
class MusicState:
    """Estado del reproductor de música."""
    is_playing: bool = False
    is_paused: bool = False
    current_file: str = ""
    position: float = 0.0
    duration: float = 0.0
    volume: int = 70


class SystemState:
    """
    Estado global del sistema. Thread-safe.
    Singleton: usar SystemState.get_instance()
    """
    _instance: Optional["SystemState"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._gps_lock = threading.Lock()
        self._metrics_lock = threading.Lock()
        self._music_lock = threading.Lock()

        self.gps = GPSState()
        self.metrics = SystemMetrics()
        self.music = MusicState()

        # Señales de control
        self.shutdown_event = threading.Event()
        self.current_app: str = "menu"

    @classmethod
    def get_instance(cls) -> "SystemState":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def update_gps(self, data):
        with self._gps_lock:
            self.gps.update_from_driver(data)

    def get_gps(self) -> GPSState:
        with self._gps_lock:
            # Retorna copia para evitar race conditions
            import copy
            return copy.copy(self.gps)

    def update_metrics(self, **kwargs):
        with self._metrics_lock:
            for k, v in kwargs.items():
                if hasattr(self.metrics, k):
                    setattr(self.metrics, k, v)
            self.metrics.last_update = time.time()

    def get_metrics(self) -> SystemMetrics:
        with self._metrics_lock:
            import copy
            return copy.copy(self.metrics)

    def update_music(self, **kwargs):
        with self._music_lock:
            for k, v in kwargs.items():
                if hasattr(self.music, k):
                    setattr(self.music, k, v)

    def get_music(self) -> MusicState:
        with self._music_lock:
            import copy
            return copy.copy(self.music)

    def request_shutdown(self):
        self.shutdown_event.set()

    def is_shutting_down(self) -> bool:
        return self.shutdown_event.is_set()
