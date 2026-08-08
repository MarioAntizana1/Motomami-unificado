#!/usr/bin/env python3
"""
video_player_app.py - Reproductor de video con framebuffer nativo.
Usa ffmpeg para extraer frames, audio por ffmpeg|aplay directo a ALSA.
Estetica tomada de la version final/ (original).
"""
import os
import sys
import time
import subprocess
import threading
from PIL import Image, ImageDraw

_SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import config_loader
from libs.fb_display import FbDisplay, _find_font, _get_fb1, _get_fb2, _get_hdmi
from libs.media_sources import discover_media_sources

VIDEO_EXT = ('.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.m4v')
VOLUME_STEP = 5
AUDIO_DEVICE = "plughw:0,0"  # HDMI (card 0), evita el default roto por PipeWire

_IS_HDMI = config_loader.DISPLAY_MODE == "hdmi"
if _IS_HDMI:
    VIDEO_W, VIDEO_H = 1280, 800   # resolucion nativa del fb HDMI (sin rescale)
else:
    VIDEO_W, VIDEO_H = 320, 240

SEARCH_FOLDERS = [
    config_loader.MOVIES_DIR,
    "/moto/movies",
    "/moto",
    "/home/motomami/moto/movies",
    "/home/motomami/moto",
]


class FileBrowser:
    def __init__(self):
        self.files = []
        self.names = []
        self.is_dir = []
        self.selected = 0
        self.playing_idx = -1
        self.scroll = 0
        self.current_folder = None
        self._hist = []
        self.refresh()

    def _find_root(self):
        for f in SEARCH_FOLDERS:
            if os.path.isdir(f):
                return f
        return config_loader.MOVIES_DIR

    def refresh(self):
        self.files = []
        self.names = []
        self.is_dir = []
        if self.current_folder is None:
            self.sources = discover_media_sources(config_loader.MOVIES_DIR, "VIDEO")
            for source in self.sources:
                self.files.append(source.path)
                self.names.append(f"[FUENTE] {source.label}")
                self.is_dir.append(True)
            self.selected = 0
            self.scroll = 0
            return
        if not os.path.isdir(self.current_folder):
            return
        dirs = []
        vids = []
        try:
            entries = sorted(os.listdir(self.current_folder), key=str.lower)
        except Exception:
            entries = []
        for e in entries:
            full = os.path.join(self.current_folder, e)
            if os.path.isdir(full):
                dirs.append((full, e))
            elif e.lower().endswith(VIDEO_EXT):
                vids.append((full, e))
        for p, n in dirs:
            self.files.append(p)
            self.names.append(n)
            self.is_dir.append(True)
        for p, n in vids:
            self.files.append(p)
            self.names.append(n)
            self.is_dir.append(False)
        self.selected = 0
        self.scroll = 0

    def get_display_list(self):
        r = []
        for i in range(self.scroll, min(self.scroll + 10, len(self.files))):
            r.append((i, self.names[i], self.is_dir[i], i == self.playing_idx))
        return r

    def move_up(self):
        if self.selected > 0:
            self.selected -= 1
        if self.selected < self.scroll:
            self.scroll = self.selected

    def move_down(self):
        if self.selected < len(self.files) - 1:
            self.selected += 1
        if self.selected >= self.scroll + 10:
            self.scroll = self.selected - 9

    def get_selected_path(self):
        if 0 <= self.selected < len(self.files):
            return self.files[self.selected]
        return None

    def get_selected_is_dir(self):
        if 0 <= self.selected < len(self.is_dir):
            return self.is_dir[self.selected]
        return False

    def set_playing(self, idx):
        self.playing_idx = idx

    def navigate_into(self):
        if not self.get_selected_is_dir():
            return False
        p = self.get_selected_path()
        if not p or not os.path.isdir(p):
            return False
        self._hist.append(self.current_folder)
        self.current_folder = p
        self.playing_idx = -1
        self.refresh()
        return True

    def navigate_up(self):
        if not self._hist:
            return False
        self.current_folder = self._hist.pop()
        self.playing_idx = -1
        self.refresh()
        return True

    def current_path_display(self):
        if self.current_folder is None:
            return "FUENTES DE VIDEO"
        p = self.current_folder
        for f in SEARCH_FOLDERS:
            if p.startswith(f):
                rel = p[len(f):]
                return f"~{rel}" if rel else os.path.basename(f)
        return p


class VideoPlayer:
    def __init__(self, frame_sink=None, raw=False):
        self.ffmpeg_proc = None
        self.audio_proc = None
        self._aplay_proc = None
        self._audio_thread = None
        self.is_playing = False
        self.is_paused = False
        self.current_file = None
        self.duration = 0.0
        self.position = 0.0
        self.volume = 70
        self._running = False
        self._thread = None
        self._frame_sink = frame_sink
        self._raw = raw
        self._frame_w = VIDEO_W
        self._frame_h = VIDEO_H
        self._frame_bytes = VIDEO_W * VIDEO_H * (2 if raw else 3)
        self.target_fps = 10
        self._seek_offset = 0.0

    def play(self, filepath):
        if not os.path.exists(filepath):
            return False
        self.stop()
        self.current_file = filepath
        self.duration = 0.0
        self.position = 0.0
        self._analyze_video(filepath)

        pix_fmt = 'rgb565le' if self._raw else 'rgb24'
        try:
            self.ffmpeg_proc = subprocess.Popen(
                ['ffmpeg', '-v', 'error', '-re',
                 '-i', filepath,
                 '-r', f'{self.target_fps}',
                 '-vf', (f'scale={VIDEO_W}:{VIDEO_H}:force_original_aspect_ratio=decrease,'
                         f'pad={VIDEO_W}:{VIDEO_H}:(ow-iw)/2:(oh-ih)/2:black'),
                 '-f', 'rawvideo',
                 '-pix_fmt', pix_fmt,
                 '-an', '-sn', '-'],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                bufsize=2048 * 1024,
            )
        except FileNotFoundError:
            print("[Video] ffmpeg no instalado")
            return False

        # Audio: ffmpeg decodifica y aplay escribe directo a ALSA (evita SDL/ffplay).
        self._start_audio(filepath)

        self.is_playing = True
        self.is_paused = False
        self._running = True
        self._seek_offset = 0.0
        self._thread = threading.Thread(target=self._render_loop, daemon=True)
        self._thread.start()
        return True

    def _start_audio(self, filepath):
        try:
            self.audio_proc = subprocess.Popen(
                ['ffmpeg', '-v', 'error', '-i', filepath,
                 '-vn', '-sn', '-ac', '2', '-ar', '48000',
                 '-f', 's16le', '-acodec', 'pcm_s16le', 'pipe:1'],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            self.audio_proc = None
            return
        try:
            self._aplay_proc = subprocess.Popen(
                ['aplay', '-D', AUDIO_DEVICE, '-r', '48000', '-c', '2',
                 '-f', 'S16_LE', '-q'],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            self.audio_proc.terminate()
            self.audio_proc = None
            return

        def _pump():
            try:
                while True:
                    chunk = self.audio_proc.stdout.read(65536)
                    if not chunk:
                        break
                    self._aplay_proc.stdin.write(chunk)
            except Exception:
                pass
            finally:
                try:
                    if self._aplay_proc and self._aplay_proc.stdin:
                        self._aplay_proc.stdin.close()
                except Exception:
                    pass

        self._audio_thread = threading.Thread(target=_pump, daemon=True)
        self._audio_thread.start()

    def _analyze_video(self, filepath):
        try:
            r = subprocess.run(
                ['ffprobe', '-v', 'error',
                 '-show_entries', 'format=duration',
                 '-of', 'default=noprint_wrappers=1:nokey=1', filepath],
                capture_output=True, text=True, timeout=10)
            if r.returncode == 0 and r.stdout.strip():
                self.duration = float(r.stdout.strip())
        except Exception:
            self.duration = 0
        self._frame_w, self._frame_h = VIDEO_W, VIDEO_H

    def _render_loop(self):
        proc = self.ffmpeg_proc
        if not proc:
            self.is_playing = False
            return
        frame_size = self._frame_bytes
        frame_n = 0
        time.sleep(0.5)
        t0 = time.time()
        try:
            while self._running and proc.poll() is None:
                if self.is_paused:
                    time.sleep(0.05)
                    continue
                raw = proc.stdout.read(frame_size)
                if not raw or len(raw) < frame_size:
                    break
                try:
                    if self._raw:
                        if self._frame_sink:
                            self._frame_sink(raw)
                    else:
                        img = Image.frombuffer('RGB', (self._frame_w, self._frame_h), raw, 'raw', 'RGB', 0, 1)
                        if self._frame_sink:
                            self._frame_sink(img)
                        else:
                            _get_fb1().show(img)
                except Exception:
                    pass
                frame_n += 1
                self.position = self._seek_offset + frame_n / float(self.target_fps)
                elapsed = time.time() - t0
                target = frame_n / float(self.target_fps)
                if elapsed < target:
                    time.sleep(target - elapsed)
                if self.duration > 0 and self.position >= self.duration:
                    break
        except Exception as e:
            print(f"[Video] Error render: {e}")
        finally:
            self._cleanup_ffmpeg()
            self.is_playing = False
            self._running = False

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

    def _cleanup_audio(self):
        if self._audio_thread and self._audio_thread.is_alive():
            self._audio_thread.join(timeout=2)
        if self.audio_proc:
            try:
                self.audio_proc.terminate()
                self.audio_proc.wait(timeout=1)
            except Exception:
                try:
                    self.audio_proc.kill()
                except Exception:
                    pass
            self.audio_proc = None
        if getattr(self, "_aplay_proc", None):
            try:
                self._aplay_proc.terminate()
                self._aplay_proc.wait(timeout=1)
            except Exception:
                try:
                    self._aplay_proc.kill()
                except Exception:
                    pass
            self._aplay_proc = None

    def stop(self):
        self._running = False
        if self.ffmpeg_proc and self.ffmpeg_proc.stdout:
            try:
                self.ffmpeg_proc.stdout.close()
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        self._cleanup_ffmpeg()
        self._cleanup_audio()
        self.is_playing = False
        self.is_paused = False
        self.position = 0

    def pause(self):
        self.is_paused = not self.is_paused
        try:
            pct = 0 if self.is_paused else self.volume
            subprocess.run(['amixer', '-c', '0', 'sset', 'PCM', f'{pct}%'],
                           capture_output=True, timeout=1)
        except Exception:
            pass

    def set_volume(self, vol):
        self.volume = max(0, min(100, vol))
        if self.is_paused:
            return
        try:
            subprocess.run(['amixer', '-c', '0', 'sset', 'PCM', f'{self.volume}%'],
                           capture_output=True, timeout=1)
        except Exception:
            pass


class VideoPlayerApp:
    def __init__(self, input_mgr, state=None):
        self._input = input_mgr
        self._state = state
        self._fb = FbDisplay(3)
        self._is_hdmi = _IS_HDMI
        self._raw_hdmi = _get_hdmi() if self._is_hdmi else None
        self._info_fb = FbDisplay(3, output="dual") if self._is_hdmi else None
        self._running = False
        self.browser = FileBrowser()
        self.player = VideoPlayer(frame_sink=self._on_video_frame, raw=self._is_hdmi)
        self.mode = 'browser'
        self.last_upd = 0

    def run(self):
        self._running = True
        self._render_browser()
        while self._running:
            now = time.time()
            evt = self._input.get_event(timeout=0.05)

            if self.mode == 'playing':
                if not self.player.is_playing:
                    self.mode = 'browser'
                    self._render_browser()
                    continue
                if now - self.last_upd >= 1.0:
                    self.last_upd = now
                    self._render_playing_info()

            if evt:
                action, _ = evt
                self._handle_action(action)
                if self.mode == 'browser':
                    self._render_browser()

            time.sleep(0.02)

        self.player.stop()
        self._fb.blank()
        self._fb.update()
        if self._raw_hdmi:
            self._raw_hdmi.blank()

    def _handle_action(self, action):
        if self.mode == 'browser':
            if action == 'UP':
                self.browser.move_up()
            elif action == 'DOWN':
                self.browser.move_down()
            elif action == 'ENTER':
                if self.browser.get_selected_is_dir():
                    self.browser.navigate_into()
                else:
                    path = self.browser.get_selected_path()
                    if path and os.path.exists(path):
                        if self._is_hdmi:
                            self._info_fb.blank()
                            self._info_fb.update()
                        else:
                            _get_fb2().show(Image.new("RGB", (320, 240), (0, 0, 0)))
                        self.player.play(path)
                        self.browser.set_playing(self.browser.selected)
                        self.mode = 'playing'
                        self.last_upd = 0
            elif action == 'BACK':
                if not self.browser.navigate_up():
                    self._running = False
        else:
            if action == 'ENTER':
                self.player.pause()
                self._render_playing_info()
            elif action == 'BACK':
                self.player.stop()
                self.mode = 'browser'
            elif action == 'UP':
                self.player.set_volume(self.player.volume + VOLUME_STEP)
                self._render_playing_info()
            elif action == 'DOWN':
                self.player.set_volume(self.player.volume - VOLUME_STEP)
                self._render_playing_info()

    def _render_browser(self):
        self._fb.blank()
        d = self._fb.draw()
        W, H = 320, 240

        # Pantalla 1: listado de videos
        folder = self.browser.current_path_display()
        d.rectangle([(0, 0), (W - 1, 22)], fill=(0, 40, 60))
        d.text((6, 3), folder, font=self._fb.font_s, fill=(0, 200, 255))
        d.line([(0, 22), (W, 22)], fill=(0, 80, 120))

        vis = self.browser.get_display_list()[:10]
        y = 26
        for idx, name, is_dir, is_playing in vis:
            if idx == self.browser.selected:
                d.rectangle([(2, y - 1), (W - 2, y + 13)], fill=(0, 60, 80), outline=(0, 200, 255))
                fg, pf = (255, 255, 255), "> "
            elif is_playing:
                fg, pf = (0, 255, 100), "> "
            elif is_dir:
                fg, pf = (100, 180, 255), "[] "
            else:
                fg, pf = (160, 160, 180), "   "
            d.text((6, y + 1), f"{pf}{name}", font=self._fb.font_xs, fill=fg)
            y += 13

        if not vis:
            d.text((10, 50), "No hay videos", font=self._fb.font, fill=(200, 100, 0))
            d.text((10, 70), "Busca en /moto o /home/motomami/movies", font=self._fb.font_xs, fill=(120, 120, 120))

        d.rectangle([(1, 1), (W - 2, H - 2)], outline=(0, 100, 150), width=1)
        d.text((4, H - 12), "ENTER=Reprod/Entrar  BACK=Atras  ^v=Navegar", font=self._fb.font_xs, fill=(80, 80, 100))

        # Pantalla 2: info del seleccionado
        ox = 320
        d.rectangle([(ox, 0), (ox + W - 1, 22)], fill=(20, 10, 30))
        d.text((ox + 6, 3), "INFO", font=self._fb.font_title, fill=(150, 100, 200))
        d.line([(ox, 22), (ox + W, 22)], fill=(40, 20, 60))

        path = self.browser.get_selected_path()
        if path:
            if self.browser.get_selected_is_dir():
                d.text((ox + 6, 30), "[DIR]", font=self._fb.font, fill=(100, 180, 255))
                d.text((ox + 6, 52), "ENTER para entrar", font=self._fb.font_s, fill=(140, 140, 160))
            else:
                name = os.path.basename(path)
                size_mb = os.path.getsize(path) / (1024 * 1024)
                d.text((ox + 6, 30), name, font=self._fb.font_s, fill=(200, 200, 255))
                d.text((ox + 6, 52), f"Tamaño: {size_mb:.1f} MB", font=self._fb.font_s, fill=(140, 140, 160))
        d.text((ox + 6, 90), "ENTER = Reproducir", font=self._fb.font_s, fill=(100, 200, 100))
        d.text((ox + 6, 108), "BACK = Volver", font=self._fb.font_s, fill=(200, 100, 100))

        d.rectangle([(ox + 1, 1), (ox + W - 2, H - 2)], outline=(80, 40, 120), width=1)
        self._fb.update()

    def _render_playing_info(self):
        img = Image.new("RGB", (320, 240), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        ft = _find_font(14)
        fs = _find_font(11)

        name = os.path.basename(self.player.current_file or "")[:20]
        status = "||" if self.player.is_paused else ">>>"
        draw.text((5, 5), f"{status} {name}", font=ft, fill=(0, 255, 120))

        dur = self.player.duration
        pos = self.player.position
        if dur > 0:
            prog = min(pos / dur, 1.0)
            bw, bx, by = 306, 7, 30
            draw.rectangle([(bx, by), (bx + bw, by + 10)], outline=(60, 60, 80))
            if prog > 0:
                draw.rectangle([(bx, by), (bx + int(bw * prog), by + 10)], fill=(0, 200, 255))

        pt = f"{int(pos // 60):02d}:{int(pos % 60):02d}"
        dt = f"{int(dur // 60):02d}:{int(dur % 60):02d}"
        pct = int((pos / dur * 100) if dur > 0 else 0)
        draw.text((7, 44), f"{pt} / {dt}  {pct}%", font=fs, fill=(200, 200, 200))
        draw.text((7, 62), f"Vol: {self.player.volume}%", font=fs, fill=(180, 180, 200))

        for i, t in enumerate(["ENTER=Play/Pausa  BACK=Detener",
                               "UP/DOWN=Vol+/-"]):
            draw.text((7, 90 + i * 14), t, font=fs, fill=(100, 100, 120))

        draw.rectangle([(1, 1), (318, 238)], outline=(0, 150, 80), width=1)
        if self._is_hdmi:
            # Info en las dos mini pantallas; el video va aparte al HDMI.
            fb = self._info_fb
            fb.blank()
            fb.image().paste(img, (0, 0))
            desc = Image.new("RGB", (320, 240), (5, 5, 10))
            dd = ImageDraw.Draw(desc)
            dd.text((8, 8), "MOTO VIDEO", font=_find_font(18), fill=(0, 220, 255))
            dd.text((8, 40), f"{os.path.basename(self.player.current_file or '')[:28]}",
                    font=fs, fill=(160, 160, 180))
            dd.text((8, 60), f"{pt} / {dt}  {pct}%", font=fs, fill=(200, 200, 200))
            dd.text((8, 80), f"Vol: {self.player.volume}%", font=fs, fill=(180, 180, 200))
            if self.player.is_paused:
                dd.text((8, 110), "PAUSADO", font=_find_font(20), fill=(255, 200, 0))
            fb.image().paste(desc, (320, 0))
            fb.update()
        else:
            _get_fb2().show(img)

    def _on_video_frame(self, data):
        """Frames de video: en HDMI bytes RGB565 directos al framebuffer,
        en mini una imagen PIL a fb1. Sin redibujado de UI por frame."""
        if not self._is_hdmi:
            img = data if isinstance(data, Image.Image) else None
            if img is not None:
                _get_fb1().show(img)
            return
        try:
            self._raw_hdmi.write_rgb565(data)
        except Exception:
            pass
