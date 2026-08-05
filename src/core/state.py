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


@dataclass
class Esp32VelocimetroState:
    """Datos del ESP32 velocímetro vía MQTT."""
    speed: float = 0.0        # km/h
    distance: float = 0.0     # km total
    distance_m: float = 0.0   # metros totales, para recorridos cortos
    odometro: float = 0.0     # km odómetro
    pulses: int = 0
    sensor_level: int = -1    # GPIO21: 0=activo, 1=reposo
    online: bool = False
    ip: str = ""
    rssi: str = ""
    id: str = ""
    last_update: float = 0.0


@dataclass
class Esp32InputState:
    """Datos del ESP32 input vía MQTT."""
    online: bool = False
    ip: str = ""
    rssi: str = ""
    id: str = ""
    left: bool = False
    right: bool = False
    emerg: bool = False
    brake: bool = False
    night: bool = False
    last_update: float = 0.0


@dataclass
class Esp32DireccionalesState:
    """Datos del ESP32 direccionales vía MQTT."""
    online: bool = False
    ip: str = ""
    rssi: str = ""
    id: str = ""
    intermitente_izq: bool = False
    intermitente_der: bool = False
    emergencia: bool = False
    frenado: bool = False
    luz_nocturna: bool = False
    intensidad: int = 0
    intensidad_nocturna: int = 0
    last_update: float = 0.0


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
        self._esp32_lock = threading.Lock()

        self.gps = GPSState()
        self.metrics = SystemMetrics()
        self.music = MusicState()
        self.esp32_velocimetro = Esp32VelocimetroState()
        self.esp32_direccionales = Esp32DireccionalesState()
        self.esp32_input = Esp32InputState()

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

    def update_esp32_velocimetro(self, **kwargs):
        with self._esp32_lock:
            for k, v in kwargs.items():
                if hasattr(self.esp32_velocimetro, k):
                    setattr(self.esp32_velocimetro, k, v)
            self.esp32_velocimetro.last_update = time.time()

    def get_esp32_velocimetro(self) -> Esp32VelocimetroState:
        with self._esp32_lock:
            import copy
            return copy.copy(self.esp32_velocimetro)

    def update_esp32_input(self, **kwargs):
        with self._esp32_lock:
            for k, v in kwargs.items():
                if hasattr(self.esp32_input, k):
                    setattr(self.esp32_input, k, v)
            self.esp32_input.last_update = time.time()

    def get_esp32_input(self) -> Esp32InputState:
        with self._esp32_lock:
            import copy
            return copy.copy(self.esp32_input)

    def update_esp32_direccionales(self, **kwargs):
        with self._esp32_lock:
            for k, v in kwargs.items():
                if hasattr(self.esp32_direccionales, k):
                    setattr(self.esp32_direccionales, k, v)
            self.esp32_direccionales.last_update = time.time()

    def get_esp32_direccionales(self) -> Esp32DireccionalesState:
        with self._esp32_lock:
            import copy
            return copy.copy(self.esp32_direccionales)

    def request_shutdown(self):
        self.shutdown_event.set()

    def is_shutting_down(self) -> bool:
        return self.shutdown_event.is_set()
