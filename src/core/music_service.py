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
    devs = ['/dev/snd/pcmC0D0p', '/dev/snd/pcmC1D0p']
    for dev in devs:
        if not os.path.exists(dev):
            continue
        for _ in range(3):
            for proc in ('wireplumber', 'pipewire-pulse', 'pulseaudio'):
                try:
                    subprocess.run(['pkill', '-9', proc], capture_output=True, timeout=2)
                except Exception:
                    pass
            try:
                out = subprocess.run(['fuser', dev], capture_output=True, text=True, timeout=2).stdout.strip()
                if not out:
                    break
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
        """Pre-carga pygame. El mixer solo se activa durante playback."""
        import pygame
        self._pygame = pygame
        print("[Music] pygame listo (mixer bajo demanda)")

    def _ensure_mixer(self):
        """Activa el mixer solo cuando se necesita reproducir."""
        if self._ok:
            return True
        _free_audio_device()
        try:
            self._pygame.mixer.pre_init(
                frequency=44100, size=-16, channels=2,
                buffer=2048, allowedchanges=1
            )
            self._pygame.mixer.init()
            self._pygame.mixer.music.set_volume(self._volume / 100.0)
            self._ok = True
            return True
        except Exception as e:
            print(f"[Music] Error init mixer: {e}")
            self._release_mixer()
            return False

    def _release_mixer(self):
        """Suelta el dispositivo de audio para que otras apps lo usen."""
        if not self._ok:
            return
        try:
            self._pygame.mixer.music.stop()
            self._pygame.mixer.quit()
        except Exception:
            pass
        self._ok = False

    def play(self, filepath: str):
        with self._lock:
            if not self._ensure_mixer():
                return False
            try:
                self._pygame.mixer.music.load(filepath)
                self._pygame.mixer.music.play()
                self._current_file = filepath
                self._is_playing = True
                self._is_paused = False
                self._duration = self._get_duration(filepath)
                self._update_state()
                print(f"[Music] Reproduciendo: {os.path.basename(filepath)}")
                return True
            except Exception as e:
                print(f"[Music] Error play: {e}")
                self._release_mixer()
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
            self._pygame.mixer.music.stop()
            self._is_playing = False
            self._is_paused = False
            self._update_state()
            self._release_mixer()

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
