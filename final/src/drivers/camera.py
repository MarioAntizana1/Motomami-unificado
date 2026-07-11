"""
camera.py - Control de la cámara Picamera2 para Raspberry Pi

Proporciona una interfaz simple para:
  - Capturar fotos
  - Obtener frames individuales (para streaming)
  - Iniciar/detener grabación de video
"""

import time
from picamera2 import Picamera2

# Configuración por defecto
CAMERA_CONFIG = {
    'resolution': (640, 480),
    'framerate': 30,
}
DEBUG = False


class Camera:
    """Control de la cámara Raspberry Pi via Picamera2."""

    def __init__(self, resolution: tuple = None, framerate: int = None):
        """
        Inicializa la cámara.

        Args:
            resolution: (width, height) en píxeles. Default (640, 480)
            framerate: FPS objetivo. Default 30
        """
        self.camera = None
        self.is_recording = False
        self._resolution = resolution or CAMERA_CONFIG['resolution']
        self._framerate = framerate or CAMERA_CONFIG['framerate']
        self._init_camera()

    def _init_camera(self):
        """Inicializa la conexión con la cámara"""
        try:
            self.camera = Picamera2()

            config = self.camera.create_video_configuration(
                main={"size": self._resolution},
            )
            self.camera.configure(config)
            self.camera.start()

            # Esperar estabilización de auto-exposición
            time.sleep(2)

            if DEBUG:
                print(f"[CAMERA] Inicializada: {self._resolution[0]}x{self._resolution[1]}")

        except Exception as e:
            print(f"[CAMERA] Error al inicializar: {e}")
            raise

    def capture_photo(self, filename: str) -> bool:
        """
        Captura una foto y la guarda en filename.

        Returns:
            bool: True si la captura fue exitosa
        """
        try:
            if not self.camera:
                print("[CAMERA] No inicializada")
                return False
            self.camera.capture_file(filename)
            if DEBUG:
                print(f"[CAMERA] Foto capturada: {filename}")
            return True
        except Exception as e:
            print(f"[CAMERA] Error capturando foto: {e}")
            return False

    def start_recording(self, filename: str) -> bool:
        """Inicia grabación de video H264."""
        try:
            if not self.camera:
                return False
            if self.is_recording:
                print("[CAMERA] Ya grabando")
                return False
            self.camera.start_recording('h264', filename)
            self.is_recording = True
            if DEBUG:
                print(f"[CAMERA] Grabando: {filename}")
            return True
        except Exception as e:
            print(f"[CAMERA] Error al iniciar grabación: {e}")
            return False

    def stop_recording(self) -> bool:
        """Detiene la grabación de video."""
        try:
            if not self.camera or not self.is_recording:
                return False
            self.camera.stop_recording()
            self.is_recording = False
            if DEBUG:
                print("[CAMERA] Grabación detenida")
            return True
        except Exception as e:
            print(f"[CAMERA] Error al detener grabación: {e}")
            return False

    def get_frame(self):
        """
        Obtiene el frame actual como numpy array.

        Returns:
            numpy.ndarray con datos de imagen, o None si hay error
        """
        try:
            if not self.camera:
                return None
            return self.camera.capture_array("main")
        except Exception as e:
            print(f"[CAMERA] Error obteniendo frame: {e}")
            return None

    def cleanup(self):
        """Libera los recursos de la cámara."""
        try:
            if self.camera:
                if self.is_recording:
                    self.stop_recording()
                self.camera.stop()
                self.camera.close()
                if DEBUG:
                    print("[CAMERA] Cerrada")
        except Exception as e:
            print(f"[CAMERA] Error en cleanup: {e}")
