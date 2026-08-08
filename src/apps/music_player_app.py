#!/usr/bin/env python3
"""
music_player_app.py - App de reproducción de música para MotoMami.
Diseño de doble pantalla:
- Pantalla 1 (Izquierda / Superior): Información de reproducción, estado, volumen, progreso.
- Pantalla 2 (Derecha / Inferior): Explorador de archivos y carpetas.
"""
import os
import sys
import time
from PIL import Image, ImageDraw

_SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from libs.fb_display import FbDisplay, _find_font
from libs.media_sources import discover_media_sources
import config_loader

AUDIO_EXT = ('.mp3', '.wav', '.flac', '.ogg')
VOLUME_STEP = 5

class MusicBrowser:
    def __init__(self, root_dir):
        self.files = []
        self.names = []
        self.is_dir = []
        self.selected = 0
        self.playing_idx = -1
        self.scroll = 0
        self.root_folder = root_dir
        self.current_folder = None
        self._hist = []
        self.refresh()

    def refresh(self):
        self.files = []
        self.names = []
        self.is_dir = []
        if self.current_folder is None:
            self.sources = discover_media_sources(self.root_folder, "MUSICA")
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
        files = []
        try:
            entries = sorted(os.listdir(self.current_folder), key=str.lower)
        except Exception:
            entries = []
        for e in entries:
            full = os.path.join(self.current_folder, e)
            if os.path.isdir(full):
                dirs.append((full, e))
            elif e.lower().endswith(AUDIO_EXT):
                files.append((full, e))
        for p, n in dirs:
            self.files.append(p)
            self.names.append(f"[DIR] {n}")
            self.is_dir.append(True)
        for p, n in files:
            self.files.append(p)
            self.names.append(n)
            self.is_dir.append(False)
        self.selected = 0
        self.scroll = 0

    def clean_name(self, n):
        if n.startswith("[DIR] "):
            return n
        return os.path.splitext(n)[0].replace('_', ' ').replace('-', ' ').strip()

    def get_display_list(self):
        r = []
        for i in range(self.scroll, min(self.scroll + 15, len(self.files))):
            r.append((i, self.clean_name(self.names[i]), i == self.playing_idx))
        return r

    def move_up(self):
        if self.selected > 0:
            self.selected -= 1
        if self.selected < self.scroll:
            self.scroll = self.selected

    def move_down(self):
        if self.selected < len(self.files) - 1:
            self.selected += 1
        if self.selected >= self.scroll + 15:
            self.scroll = self.selected - 14

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
            return "FUENTES DE MUSICA"
        p = self.current_folder
        if p.startswith(self.root_folder):
            rel = p[len(self.root_folder):]
            return f"~{rel}" if rel else "~/music"
        return p


class MusicPlayerApp:
    def __init__(self, input_mgr, state=None, music_svc=None):
        self._input = input_mgr
        self._state = state
        self._music = music_svc
        self._fb = FbDisplay(3)  # Dual screen canvas 640x240
        self._running = False
        
        self._music_dir = config_loader.MUSIC_DIR
        os.makedirs(self._music_dir, exist_ok=True)
        
        self.browser = MusicBrowser(self._music_dir)
        self.last_upd = 0

    def run(self):
        self._running = True
        
        # Si ya está sonando una canción al entrar
        if self._music and self._music.is_playing and self._music.current_file:
            # Buscar si el archivo actual está en la carpeta actual del navegador
            curr_dir = os.path.dirname(self._music.current_file)
            if os.path.exists(curr_dir):
                self.browser.current_folder = curr_dir
                self.browser.refresh()
                curr_name = os.path.basename(self._music.current_file)
                for idx, path in enumerate(self.browser.files):
                    if os.path.basename(path) == curr_name:
                        self.browser.selected = idx
                        self.browser.playing_idx = idx
                        # Ajustar scroll
                        if idx >= 8:
                            self.browser.scroll = idx - 7
                        break

        self._render()

        while self._running:
            evt = self._input.get_event(timeout=0.05)
            
            # Auto-reproducir siguiente si termina
            if self._music and self._music.is_playing and self._music.is_finished():
                self._play_next()
                self._render()

            if evt:
                action, _ = evt
                self._handle_action(action)
                self._render()
            else:
                # Actualizar progreso cada segundo
                now = time.time()
                if self._music and self._music.is_playing and not self._music.is_paused:
                    if now - self.last_upd >= 1.0:
                        self.last_upd = now
                        self._render()

        self._fb.blank()
        self._fb.update()
        if self._music and self._music.is_playing:
            self._music.stop()

    def _play_selected(self):
        p = self.browser.get_selected_path()
        if p and os.path.exists(p) and not self.browser.get_selected_is_dir():
            if self._music:
                self._music.stop()
                time.sleep(0.05)
                if self._music.play(p):
                    self.browser.set_playing(self.browser.selected)

    def _play_next(self):
        ai = [i for i, d in enumerate(self.browser.is_dir) if not d]
        if not ai:
            return
        try:
            # Buscar el siguiente archivo de música en el directorio actual
            curr_idx = self.browser.playing_idx
            next_pos = (ai.index(curr_idx) + 1) % len(ai)
            n = ai[next_pos]
        except ValueError:
            n = ai[0]
        self.browser.selected = n
        if n >= self.browser.scroll + 8 or n < self.browser.scroll:
            self.browser.scroll = max(0, n - 7)
        self._play_selected()

    def _handle_action(self, action):
        is_playing_active = self._music and self._music.is_playing and not self._music.is_paused

        if action == 'UP':
            if is_playing_active:
                self._music.set_volume(self._music.volume + VOLUME_STEP)
            else:
                self.browser.move_up()
        elif action == 'DOWN':
            if is_playing_active:
                self._music.set_volume(self._music.volume - VOLUME_STEP)
            else:
                self.browser.move_down()
        elif action == 'LEFT':
            if self._music and self._music.is_playing:
                self._music.seek(-10)
        elif action == 'RIGHT':
            if self._music and self._music.is_playing:
                self._music.seek(10)
        elif action == 'ENTER':
            if self.browser.get_selected_is_dir():
                self.browser.navigate_into()
            else:
                selected_path = self.browser.get_selected_path()
                if self._music:
                    if self._music.current_file == selected_path and self._music.is_playing:
                        self._music.stop()
                        self.browser.set_playing(-1)
                    else:
                        self._play_selected()
        elif action == 'BACK':
            if not self.browser.navigate_up():
                self._running = False

    def _fmt_time(self, s):
        return f"{int(s//60):02d}:{int(s%60):02d}"

    def _render(self):
        self._fb.blank()
        d = self._fb.draw()
        D = (80, 80, 80)
        
        W, H = 640, 400

        # Fondo oscuro para ambas pantallas
        d.rectangle([(0, 0), (W - 1, H - 1)], fill=(0, 0, 8))
        # Línea divisoria central
        d.line([(319, 0), (319, H - 1)], fill=D, width=2)

        # ─── PANTALLA 1 (IZQ / SUPERIOR): REPRODUCTOR ───
        # Header
        d.rectangle([(0, 0), (318, 27)], fill=(80, 20, 120))
        d.text((8, 4), "♪ REPRODUCIENDO", font=self._fb.font_title, fill=(255, 255, 255))
        
        y = 36
        curr_file = self._music.current_file if self._music else ""
        if curr_file:
            t = self.browser.clean_name(os.path.basename(curr_file))
        else:
            t = "---"
        d.text((8, y), t, font=self._fb.font_s, fill=(200, 180, 255))
        y += 15
        
        # Cantidad de canciones en directorio actual
        total_songs = sum(1 for x in self.browser.is_dir if not x)
        d.text((8, y), f"{total_songs} canciones en carpeta", font=self._fb.font_s, fill=(130, 130, 160))
        
        # Barra de progreso
        y = 78
        dur = self._music.duration if self._music else 0.0
        pos = self._music.get_position() if (self._music and self._music.is_playing) else 0.0
        pct = int(pos / dur * 100) if (dur > 0) else 0
        bw = 302
        
        d.rectangle([(8, y), (8 + bw, y + 12)], fill=(20, 20, 40), outline=(60, 60, 80))
        if pct > 0:
            d.rectangle([(8, y), (8 + int(bw * pct / 100), y + 12)], fill=(200, 100, 255))
            
        d.text((8, y + 14), self._fmt_time(pos), font=self._fb.font_s, fill=(180, 180, 200))
        d.text((260, y + 14), self._fmt_time(dur), font=self._fb.font_s, fill=(180, 180, 200))
        d.text((140, y + 14), f"{pct}%", font=self._fb.font_s, fill=(200, 180, 255))
        
        # Estado del reproductor
        y = 112
        if self._music and self._music.is_playing:
            st, sc = ("PAUSADO", (255, 200, 50)) if self._music.is_paused else ("▶ REPRODUCIENDO", (100, 255, 100))
        else:
            st, sc = ("■ DETENIDO", (200, 100, 100))
            
        d.text((80, y), st, font=self._fb.font, fill=sc)
        
        # Volumen
        vol = self._music.volume if self._music else 0
        d.text((8, y + 28), f"Vol: {vol}%", font=self._fb.font_s, fill=(180, 180, 200))
        
        # Ayuda
        for i, h in enumerate([
            "ENTER: Play/Stop  BACK: Atras",
            "<- ->: Seek  UP/DOWN: Vol en play",
            "Arriba/Abajo: Navegar lista (en pausa)"
        ]):
            d.text((8, 330 + i * 14), h, font=self._fb.font_s, fill=(100, 100, 130))

        # ─── PANTALLA 2 (DER / INFERIOR): EXPLORADOR ───
        ox = 321
        p = self.browser.current_path_display()
        d.rectangle([(ox, 0), (ox + 318, 23)], fill=(30, 15, 50))
        d.text((ox + 8, 3), p, font=self._fb.font_xs, fill=(200, 150, 255))
        d.line([(ox, 23), (ox + 318, 23)], fill=(60, 30, 80))
        
        vis = self.browser.get_display_list()[:15]
        yy = 28
        for i, nm, pl in vis:
            isd = i < len(self.browser.is_dir) and self.browser.is_dir[i]
            pf = "  "
            fg = (100, 130, 200) if isd else (140, 140, 160)
            
            # Si es el elemento seleccionado por el cursor
            if i == self.browser.selected:
                d.rectangle([(ox + 2, yy - 1), (ox + 316, yy + 22)], fill=(40, 20, 60), outline=(200, 100, 255))
                pf = "> "
                fg = (255, 255, 255)
                
            # Si este elemento es el que se está reproduciendo actualmente
            if pl:
                fg = (100, 255, 100)
                pf = "▶ " if (self._music and not self._music.is_paused) else "⏸ "
                
            d.text((ox + 8, yy + 3), f"{pf}{nm}", font=self._fb.font_xs, fill=fg)
            yy += 24
            
        if not vis:
            d.text((ox + 10, 50), "Carpeta vacia", font=self._fb.font, fill=(200, 100, 0))
            
        # Canción sonando actualmente mostrada en footer del explorador
        if self._music and self._music.is_playing and curr_file:
            n2 = self.browser.clean_name(os.path.basename(curr_file))
            d.text((ox + 4, H - 16), f"Now: {n2}", font=self._fb.font_xs, fill=(100, 200, 100))
            
        self._fb.update()
