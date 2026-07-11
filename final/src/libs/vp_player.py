"""vp_player.py - Reproductor de video en pantalla ST7789"""
import os
import time
import subprocess
import threading
from PIL import Image


class VideoPlayer:
    """Reproduce video en ST7789 usando ffmpeg para extraer frames.
    Audio por ALSA/DAC Fiio.

    Escala el video manteniendo aspect ratio para que entre en 240px de ancho.
    Frame rate: 30 fps (configurable).
    """

    def __init__(self, audio_mgr, st7789_display):
        self.audio = audio_mgr
        self.display = st7789_display  # DisplayST7789
        self.ffmpeg_proc = None
        self.ffplay_proc = None

        self.is_playing = False
        self.is_paused = False
        self.current_file = None
        self.duration = 0.0
        self.position = 0.0
        self.volume = 80
        self.fps = 10  # FPS objetivo

        self._running = False
        self._thread = None
        self._frame_w = 240
        self._frame_h = 320
        self.target_fps = 10  # FPS visualización real (Pi Zero 2W no da para 30)
        self._seek_offset = 0.0  # Posicion absoluta donde empieza el segmento actual

    # ------------------------------------------------------------------
    def play(self, filepath):
        """Analiza el video, escala, y lanza reproduccion."""
        if not os.path.exists(filepath):
            print(f"[Player] No existe: {filepath}")
            return False

        self.stop()
        self.current_file = filepath
        self.duration = 0.0
        self.position = 0.0

        # Obtener dimensiones del video y escalar
        self._analyze_video(filepath)

        print(f"[Player] >> {os.path.basename(filepath)} "
              f"-> {self._frame_w}x{self._frame_h} @ {self.fps}fps")

        # --- ffmpeg: frames -> ST7789 ---
        try:
            self.ffmpeg_proc = subprocess.Popen(
                [
                    'ffmpeg', '-v', 'error',
                    '-re',
                    '-i', filepath,
                    '-r', str(self.fps),
                    '-f', 'rawvideo',
                    '-pix_fmt', 'rgb24',
                    '-s', f'{self._frame_w}x{self._frame_h}',
                    '-an', '-sn',
                    '-',
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=2048 * 2048, # buffer grande para evitar bloqueos en lectura de frames 1048 anterior, pero en videos de alta resolucion puede no ser suficiente, asi que se aumento a 2048*2048
            )
        except FileNotFoundError:
            print("[Player] ERROR: ffmpeg no instalado. sudo apt install ffmpeg")
            return False

        # --- ffplay: solo audio ---
        try:
            env = os.environ.copy()
            if self.audio and self.audio.device_name:
                card = self.audio.device_name.split(':')[0].replace('hw:', '')
                env['ALSA_CARD'] = card
                print(f"[Player] Audio: ALSA_CARD={card}")

            self.ffplay_proc = subprocess.Popen(
                ['ffplay', '-v', 'error', '-nodisp', '-autoexit', '-vn', '-sn',
                 '-fflags', 'nobuffer', filepath],
                env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            print("[Player] ffplay no disponible, solo video")
            self.ffplay_proc = None

        # Hilo de renderizado
        self.is_playing = True
        self.is_paused = False
        self._running = True
        self._seek_offset = 0.0
        self._thread = threading.Thread(target=self._render_loop, daemon=True)
        self._thread.start()

        print("[Player] Reproduciendo...")
        return True

    # ------------------------------------------------------------------
    def _analyze_video(self, filepath):
        """Obtiene dimensiones y duracion, calcula escala para 240px ancho."""
        # Duracion
        try:
            r = subprocess.run([
                'ffprobe', '-v', 'error',
                '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1', filepath,
            ], capture_output=True, text=True, timeout=10)
            if r.returncode == 0 and r.stdout.strip():
                self.duration = float(r.stdout.strip())
        except Exception:
            self.duration = 0

        # Dimensiones y FPS nativo
        vw, vh = 320, 240  # valores por defecto
        try:
            r = subprocess.run([
                'ffprobe', '-v', 'error',
                '-select_streams', 'v:0',
                '-show_entries', 'stream=width,height,r_frame_rate',
                '-of', 'csv=p=0', filepath,
            ], capture_output=True, text=True, timeout=10)
            if r.returncode == 0 and r.stdout.strip():
                parts = r.stdout.strip().split(',')
                if len(parts) >= 2:
                    vw, vh = int(parts[0]), int(parts[1])
                if len(parts) >= 3:
                    fps_str = parts[2]
                    if '/' in fps_str:
                        num, den = fps_str.split('/')
                        if float(den) > 0:
                            native_fps = float(num) / float(den)
                            self.fps = min(30.0, native_fps)
                    else:
                        self.fps = min(30.0, float(fps_str))
        except Exception:
            pass

        # Escalar: ancho maximo 240, alto mantiene proporcion
        DISP_W, DISP_H = 240, 320
        scale = min(DISP_W / vw, DISP_H / vh)
        self._frame_w = max(2, int(vw * scale) - (int(vw * scale) % 2))
        self._frame_h = max(2, int(vh * scale) - (int(vh * scale) % 2))

        print(f"[Player] Video original: {vw}x{vh}, "
              f"escalado: {self._frame_w}x{self._frame_h}, "
              f"duracion: {self.duration:.1f}s, FPS: {self.fps:.2f}")

    # ------------------------------------------------------------------
    def _render_loop(self):
            """Bucle que lee frames de ffmpeg y los muestra en ST7789.

            Usa un step fijo (self.fps / target_fps) para descartar frames
            de forma UNIFORME cuando el video tiene más FPS de los que
            podemos mostrar. Así el frame drop es constante y no se nota.
            """
            proc = self.ffmpeg_proc
            if not proc:
                self.is_playing = False
                return

            frame_size = self._frame_w * self._frame_h * 3
            frame_n = 0

            # Calcular step fijo: 1 = sin descarte, 2 = 1 de cada 2, etc.
            step = max(1, round(self.fps / self.target_fps))

            time.sleep(0.5)  # respiro para ffplay / SD
            t0 = time.time()

            try:
                while self._running and proc.poll() is None:
                    if self.is_paused:
                        time.sleep(0.05)
                        continue

                    raw = proc.stdout.read(frame_size)
                    if not raw or len(raw) < frame_size:
                        break

                    # --- Mostrar solo si toca según el step fijo ---
                    should_show = (frame_n % step == 0)

                    if should_show:
                        try:
                            img = Image.frombuffer(
                                'RGB', (self._frame_w, self._frame_h), raw,
                                'raw', 'RGB', 0, 1)

                            # Centrar si el frame escalado no llena la pantalla
                            if self._frame_w < 240 or self._frame_h < 320:
                                full = Image.new('RGB', (240, 320), (0, 0, 0))
                                x = (240 - self._frame_w) // 2
                                y = (320 - self._frame_h) // 2
                                full.paste(img, (x, y))
                                img = full

                            if self.display:
                                self.display.show_image(img)
                        except Exception:
                            pass  # un frame corrupto no para la reproducción

                    frame_n += 1
                    self.position = self._seek_offset + frame_n / self.fps

                    # --- Control de ritmo ---
                    # Dormir lo necesario para mantener el paso,
                    # incluso si hemos saltado frames.
                    elapsed = time.time() - t0
                    target = frame_n / self.fps
                    if elapsed < target:
                        time.sleep(target - elapsed)

                    # Fin del video
                    if self.duration > 0 and self.position >= self.duration:
                        break

            except Exception as e:
                print(f"[Player] Error render: {e}")
            finally:
                self._cleanup_ffmpeg()
                self.is_playing = False
                self._running = False
                print("[Player] Fin video")
    # ------------------------------------------------------------------
    def _cleanup_ffmpeg(self):
        if self.ffmpeg_proc:
            try:
                if self.ffmpeg_proc.stdout:
                    self.ffmpeg_proc.stdout.close()
                self.ffmpeg_proc.terminate()
                self.ffmpeg_proc.wait(timeout=1)
            except Exception:
                try:
                    self.ffmpeg_proc.kill()
                except Exception:
                    pass
            self.ffmpeg_proc = None

    def _cleanup_ffplay(self):
        if self.ffplay_proc:
            try:
                self.ffplay_proc.terminate()
                self.ffplay_proc.wait(timeout=1)
            except Exception:
                try:
                    self.ffplay_proc.kill()
                except Exception:
                    pass
            self.ffplay_proc = None

    # ------------------------------------------------------------------
    def pause(self):
        self.is_paused = not self.is_paused
        print(f"[Player] {'Pausa' if self.is_paused else 'Reanudar'}")

    def stop(self):
        """Detiene todo inmediatamente."""
        print("[Player] Deteniendo hilo de render...")
        self._running = False  # 1. Senal al hilo para que salga del bucle

        # 2. Cerrar stdout de ffmpeg para desbloquear el read() bloqueante en el hilo
        if self.ffmpeg_proc and self.ffmpeg_proc.stdout:
            try:
                self.ffmpeg_proc.stdout.close()
            except Exception:
                pass

        # 3. Esperar al hilo de render con suficiente tiempo (Pi Zero 2W es lento)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
            if self._thread.is_alive():
                print("[Player] ADVERTENCIA: hilo de render no termino en 3s")

        # 4. Ahora es seguro matar los procesos (el hilo ya no los usa)
        self._cleanup_ffmpeg()
        self._cleanup_ffplay()

        self.is_playing = False
        self.is_paused = False
        self.position = 0
        self.ffmpeg_proc = None
        self.ffplay_proc = None
        print("[Player] Detenido")

    def seek(self, seconds):
        """Seek relativo (+/-). Reinicia ffmpeg desde la nueva posicion."""
        if not self.is_playing or not self.current_file:
            return
        new_pos = max(0.0, min(self.position + seconds,
                               self.duration - 1 if self.duration > 0 else self.position + seconds))
        self._seek_to(new_pos)

    def _seek_to(self, position):
        """Reinicia ffmpeg y ffplay desde una posicion absoluta en segundos."""
        print(f"[Player] Seek -> {position:.1f}s")
        was_paused = self.is_paused

        # Detener hilo de render
        self._running = False
        if self.ffmpeg_proc and self.ffmpeg_proc.stdout:
            try:
                self.ffmpeg_proc.stdout.close()
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

        self._cleanup_ffmpeg()
        self._cleanup_ffplay()

        self._seek_offset = position
        self.position = position

        # Relanzar ffmpeg desde la nueva posicion
        try:
            self.ffmpeg_proc = subprocess.Popen(
                [
                    'ffmpeg', '-v', 'error',
                    '-re',
                    '-ss', f'{position:.3f}',
                    '-i', self.current_file,
                    '-r', str(self.fps),
                    '-f', 'rawvideo',
                    '-pix_fmt', 'rgb24',
                    '-s', f'{self._frame_w}x{self._frame_h}',
                    '-an', '-sn',
                    '-',
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=1024 * 1024,
            )
        except FileNotFoundError:
            return

        # Relanzar ffplay desde la nueva posicion
        try:
            env = os.environ.copy()
            if self.audio and self.audio.device_name:
                card = self.audio.device_name.split(':')[0].replace('hw:', '')
                env['ALSA_CARD'] = card
            self.ffplay_proc = subprocess.Popen(
                ['ffplay', '-v', 'error', '-nodisp', '-autoexit', '-vn', '-sn',
                 '-fflags', 'nobuffer', '-ss', f'{position:.3f}', self.current_file],
                env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            self.ffplay_proc = None

        # Relanzar hilo de render
        self.is_paused = was_paused
        self._running = True
        self.is_playing = True  # <-- AÑADIDO: el hilo anterior lo dejo en False al morir
        self._thread = threading.Thread(target=self._render_loop, daemon=True)
        self._thread.start()
        print(f"[Player] Seek OK @ {position:.1f}s")

    def set_volume(self, vol):
        self.volume = max(0, min(100, vol))
        try:
            card = '0'
            if self.audio and self.audio.device_name:
                card = self.audio.device_name.split(':')[0].replace('hw:', '')
            subprocess.run(
                ['amixer', '-c', card, 'sset', 'PCM', f'{self.volume}%'],
                capture_output=True, timeout=1)
        except Exception:
            pass
