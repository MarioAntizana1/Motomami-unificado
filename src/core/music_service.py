"""
music_service.py - Servicio de música que persiste entre apps.
La música NO se detiene al cambiar de app (salvo que el usuario lo pida).
"""
import threading
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config_loader import MUSIC_DIR

AUDIO_EXTENSIONS = ('.mp3', '.wav', '.flac', '.ogg')


def _free_audio_device():
    """Libera el DAC USB si está ocupado."""
    import subprocess
    dev = '/dev/snd/pcmC1D0p'
    if not os.path.exists(dev):
        return
    for _ in range(3):
        for proc in ('wireplumber', 'pipewire-pulse'):
            try:
                subprocess.run(['pkill', '-9', proc], capture_output=True, timeout=2)
            except Exception:
                pass
        try:
            out = subprocess.run(['fuser', dev], capture_output=True, text=True, timeout=2).stdout.strip()
            if not out:
                return
            for tok in out.split():
                try:
                    os.kill(int(tok), 9)
                except Exception:
                    pass
            time.sleep(0.3)
        except Exception:
            pass


class MusicService:
    """
    Controlador de reproducción de audio.
    Usa pygame.mixer. Thread-safe vía Lock.
    """

    def __init__(self, state=None):
        self._state = state
        self._lock = threading.Lock()
        self._ok = False
        self._current_file = ""
        self._volume = 70
        self._is_playing = False
        self._is_paused = False
        self._duration = 0.0

    def init(self):
        """Inicializa pygame.mixer. Llamar una vez al arrancar."""
        _free_audio_device()
        try:
            import pygame
            pygame.mixer.pre_init(
                frequency=22050, size=-16, channels=2,
                buffer=4096, allowedchanges=0
            )
            pygame.mixer.init()
            pygame.mixer.music.set_volume(self._volume / 100.0)
            self._ok = True
            print(f"[Music] Audio listo. Vol={self._volume}%")
        except Exception as e:
            print(f"[Music] Error init pygame: {e}")

    def play(self, filepath: str):
        with self._lock:
            if not self._ok:
                return False
            try:
                import pygame
                pygame.mixer.music.load(filepath)
                pygame.mixer.music.play()
                self._current_file = filepath
                self._is_playing = True
                self._is_paused = False
                self._duration = self._get_duration(filepath)
                self._update_state()
                print(f"[Music] Reproduciendo: {os.path.basename(filepath)}")
                return True
            except Exception as e:
                print(f"[Music] Error play: {e}")
                return False

    def pause_toggle(self):
        with self._lock:
            if not self._ok or not self._is_playing:
                return
            import pygame
            if self._is_paused:
                pygame.mixer.music.unpause()
                self._is_paused = False
            else:
                pygame.mixer.music.pause()
                self._is_paused = True
            self._update_state()

    def stop(self):
        with self._lock:
            if not self._ok:
                return
            import pygame
            pygame.mixer.music.stop()
            self._is_playing = False
            self._is_paused = False
            self._update_state()

    def seek(self, seconds: float):
        with self._lock:
            if not self._ok or not self._is_playing:
                return
            try:
                import pygame
                current_pos = self.get_position()
                new_pos = max(0.0, min(current_pos + seconds, self._duration))
                pygame.mixer.music.rewind()
                pygame.mixer.music.set_pos(new_pos)
                # pygame doesn't update get_pos immediately after set_pos, but it plays from there
            except Exception as e:
                print(f"[Music] Error seek: {e}")

    def set_volume(self, vol: int):
        with self._lock:
            self._volume = max(0, min(100, vol))
            if self._ok:
                import pygame
                pygame.mixer.music.set_volume(self._volume / 100.0)
            self._update_state()

    def get_position(self) -> float:
        if not self._ok:
            return 0.0
        try:
            import pygame
            ms = pygame.mixer.music.get_pos()
            return ms / 1000.0 if ms >= 0 else 0.0
        except Exception:
            return 0.0

    def is_finished(self) -> bool:
        if not self._ok or not self._is_playing or self._is_paused:
            return False
        try:
            import pygame
            return not pygame.mixer.music.get_busy()
        except Exception:
            return True

    def quit(self):
        try:
            import pygame
            pygame.mixer.music.stop()
            pygame.mixer.quit()
        except Exception:
            pass
        self._ok = False

    def _get_duration(self, fp: str) -> float:
        try:
            import mutagen
            f = mutagen.File(fp)
            if f and f.info:
                return f.info.length
        except Exception:
            pass
        return 0.0

    def _update_state(self):
        """Actualiza MusicState en SystemState."""
        if self._state:
            self._state.update_music(
                is_playing=self._is_playing,
                is_paused=self._is_paused,
                current_file=self._current_file,
                duration=self._duration,
                volume=self._volume,
            )

    @property
    def current_file(self) -> str:
        return self._current_file

    @property
    def volume(self) -> int:
        return self._volume

    @property
    def is_playing(self) -> bool:
        return self._is_playing

    @property
    def is_paused(self) -> bool:
        return self._is_paused

    @property
    def duration(self) -> float:
        return self._duration
