#!/usr/bin/env python3
"""
video_player.py - REPRODUCTOR DE VIDEO
=======================================
Reproduce MP4 en Raspberry Pi Zero 2W.

Hardware:
  - Mando Xbox Bluetooth
  - DAC USB Fiio (audio)
  - 2 pantallas ST7789 via SPI

Pantalla #1 (GPIO17): Video / Navegador
Pantalla #2 (GPIO24): Info de reproduccion

Uso:
  cd src && sudo python3 apps/video_player.py
Videos en:  movies/   (junto al script)
"""

import os
import sys

# ── Asegurar rutas de módulos locales ──
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_BASE_DIR = os.path.dirname(_THIS_DIR)  # src/
for _p in [os.path.join(_BASE_DIR, 'lib')]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import time

# ── Keyboard fallback (non-blocking stdin) ──
import select
import termios
import tty

# Keyboard key mappings (when Xbox controller is not connected)
# These are designed to be ergonomic on a phone-style keyboard or compact layout
KEY_MAP = {
    'k': 'UP',         # K = Up
    'j': 'DOWN',       # J = Down
    'h': 'LEFT',       # H = Left
    'l': 'RIGHT',      # L = Right
    ' ': 'ENTER',      # Space = A/Enter
    '\x1b': 'BACK',    # Esc = B/Back
    'a': 'X',          # A = X (volume -)
    's': 'Y',          # S = Y (volume +)
    'z': 'L3',         # Z = seek -15s
    'c': 'R3',         # C = seek +15s
    'q': 'QUIT',       # Q = quit
}


def _init_keyboard():
    """
    Set stdin to non-blocking raw mode for keyboard input.
    Returns the original terminal settings so they can be restored.
    """
    try:
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        tty.setraw(fd)
        return old_settings
    except Exception:
        return None


def _restore_keyboard(old_settings):
    """Restore terminal settings."""
    if old_settings is None:
        return
    try:
        fd = sys.stdin.fileno()
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    except Exception:
        pass


def _read_key():
    """Non-blocking keyboard read. Returns a single character or None."""
    try:
        if select.select([sys.stdin], [], [], 0.0)[0]:
            ch = sys.stdin.read(1)
            # Map uppercase to lowercase for simplicity
            if ch and 'A' <= ch <= 'Z':
                ch = ch.lower()
            return ch
    except Exception:
        pass
    return None


from vp_config import VOLUME_STEP
from vp_audio import AudioManager
from vp_controller import XboxController
from fb_compat import DualDisplay
from vp_browser import FileBrowser
from vp_player import VideoPlayer


class App:
    def __init__(self):
        print("=" * 45)
        print("  REPRODUCTOR DE VIDEO")
        print("  Xbox + DAC Fiio + ST7789 x2")
        print("=" * 45)

        self.audio = AudioManager()
        self.dual = DualDisplay()
        self.browser = FileBrowser()

        self.main_disp = self.dual.get_main()       # #1 Display via daemon
        self.info_disp = self.dual.get_secondary()  # #2 Display via daemon

        self.player = VideoPlayer(self.audio, self.main_disp)
        self.controller = XboxController()

        try:
            import board
            import digitalio
            self.btn_back = digitalio.DigitalInOut(board.D16)
            self.btn_back.direction = digitalio.Direction.INPUT
            self.btn_back.pull = digitalio.Pull.DOWN

            # Full GPIO button bank
            self.gpio_buttons = {}
            BTN_MAP = {
                'UP': board.D13,
                'DOWN': board.D26,
                'LEFT': board.D6,
                'RIGHT': board.D5,
                'ENTER': board.D12,
                'BACK': board.D16,
            }
            for name, pin in BTN_MAP.items():
                try:
                    btn = None
                    for _retry in range(5):
                        try:
                            btn = digitalio.DigitalInOut(pin)
                            break
                        except Exception:
                            time.sleep(0.1)
                    else:
                        print('[Btn] GPIO busy after retries')
                    if btn:
                        btn.direction = digitalio.Direction.INPUT
                        btn.pull = digitalio.Pull.DOWN
                        self.gpio_buttons[name] = btn
                except:
                    pass
            self.btn_prev = {k: False for k in self.gpio_buttons}
        except Exception:
            self.btn_back = None
            self.gpio_buttons = {}
            self.btn_prev = {}

        self.running = False
        self.mode = 'browser'
        self.show_menu = False
        self.menu_idx = 0
        self.menu_items = ['Reproducir', 'Refrescar', 'Salir']
        
        # Keyboard fallback
        self._kb_settings = _init_keyboard()
        self._xbox_available = False

    # ------------------------------------------------------------------
    def run(self):
        self._show_startup()

        if self.controller.connect():
            self.controller.start()
            self._xbox_available = True
            print("[App] Mando Xbox conectado")
        else:
            self._xbox_available = False
            print("[App] Mando Xbox NO disponible - usando teclado")

        self._refresh_browser()
        self.running = True

        last_update = 0
        
        if self._xbox_available:
            print("[App] A=Play  B=Menu  X=Vol-  Y=Vol+  Flechas=Navegar")
        else:
            print("[App] TECLADO: K=Up J=Down H=Left L=Right Space=Play/A Esc=Salir")
            print("[App]          A=Vol- S=Vol+ Z=Rewind C=Forward Q=Quit")

        while self.running:
            now = time.time()
            
            # Botón Físico Atrás
            if self.btn_back and self.btn_back.value:
                print("[App] Botón Físico Atrás presionado. Saliendo...")
                self.running = False
                continue

            # GPIO buttons (rising edge) - always check
            for name, btn in self.gpio_buttons.items():
                try:
                    current = btn.value
                except:
                    continue
                if current and not self.btn_prev.get(name, False):
                    self.btn_prev[name] = True
                    if name == 'UP': self._handle_keyboard('UP')
                    elif name == 'DOWN': self._handle_keyboard('DOWN')
                    elif name == 'LEFT': self._handle_keyboard('LEFT')
                    elif name == 'RIGHT': self._handle_keyboard('RIGHT')
                    elif name == 'ENTER': self._handle_keyboard('ENTER')
                    elif name == 'BACK': self._handle_keyboard('BACK')
                self.btn_prev[name] = current

            # Procesar eventos del mando (NO bloqueante) - solo si disponible
            if self._xbox_available:
                evt = self.controller.get_event(0.01)
                while evt:
                    if evt[0] == 'btn':
                        self._handle_btn(evt[1])
                    evt = self.controller.get_event(0.01)
            else:
                # Fallback: leer teclado
                ch = _read_key()
                if ch and ch in KEY_MAP:
                    self._handle_keyboard(KEY_MAP[ch])

            # Si el video termino solo
            if self.mode == 'playing' and not self.player.is_playing:
                print("[App] Video terminado")
                self.mode = 'browser'
                self._resume_info_display()  # Reactivar pantalla #2
                self._refresh_browser()

            # Actualizar pantalla #2 cada 1s durante reproduccion
            if self.mode == 'playing' and now - last_update > 1.0:
                last_update = now
                self._update_info_display()

            time.sleep(0.02)

        self.player.stop()
        self.controller.stop()
        _restore_keyboard(self._kb_settings)
        self.dual.clear_all()
        print("[App] Fin.")

    # ------------------------------------------------------------------
    def _show_startup(self):
        if self.main_disp:
            self.main_disp.show_message("Video Player", 5, (0, 200, 255))
            self.main_disp.show_message("Cargando...", 30)
        if self.info_disp:
            self.info_disp.show_message("Info Panel", 80, (100, 180, 255))

    # ------------------------------------------------------------------
    def _resume_info_display(self):
        """Reactiva la pantalla #2 y garantiza un pequeño margen antes de dibujar."""
        if self.info_disp:
            self.info_disp.resume()
            time.sleep(0.1)  # Margen para que el bus SPI quede completamente libre

    def _refresh_browser(self):
        """Redibuja el navegador en #1 e info en #2."""
        if self.main_disp:
            self.main_disp.show_files(
                self.browser.get_display_list(),
                self.browser.selected,
                self.browser.playing_idx,
                self.browser.scroll,
                self.browser.current_folder,
            )
        if self.info_disp:
            n = len(self.browser.files)
            sel = os.path.basename(self.browser.get_selected_path() or "---")
            txt = (
                f"  NAVEGADOR\n\n"
                f"  Videos: {n}\n"
                f"  Sel: {sel[:16]}\n\n"
                f"  A = Reproducir\n"
                f"  B = Menu\n"
                f"  Flec = Navegar"
            )
            self.info_disp.show_message(txt, 5, (150, 200, 255))

    # ------------------------------------------------------------------
    def _update_info_display(self):
        """Actualiza la pantalla #2 con informacion de reproduccion."""
        if not self.info_disp or not self.player.current_file:
            return

        name = os.path.basename(self.player.current_file)[:16]
        dur = self.player.duration
        pos = self.player.position
        vol = self.player.volume

        pt = f"{int(pos//60):02d}:{int(pos%60):02d}"
        dt = f"{int(dur//60):02d}:{int(dur%60):02d}"
        pct = int((pos / dur * 100) if dur > 0 else 0)

        status = "| |" if self.player.is_paused else ">>>"
        bar = '#' * (pct // 5) + '.' * (20 - pct // 5)

        txt = (
            f"  {status}\n"
            f"  {name}\n\n"
            f"  [{bar}]\n"
            f"  {pt} / {dt}  {pct}%\n"
            f"  Vol: {vol}%\n\n"
            f"  A = Pausa\n"
            f"  B = Detener\n"
            f"  X/Y = Vol+/-"
        )
        self.info_disp.show_message(txt, 3, (0, 255, 120))

    # ------------------------------------------------------------------
    def _handle_btn(self, btn):
        if btn == XboxController.A:
            if self.mode == 'browser':
                if self.show_menu:
                    self._exec_menu()
                else:
                    self._play_selected()
            else:
                self.player.pause()
                self._update_info_display()

        elif btn == XboxController.B:
            if self.mode == 'browser':
                self.show_menu = not self.show_menu
            else:
                # DETENER Y VOLVER
                print("[App] Deteniendo...")
                self.player.stop()
                self.mode = 'browser'
                # Esperar a que el hilo de render termine por completo
                _t = time.time()
                while self.player.is_playing and (time.time() - _t) < 4.0:
                    time.sleep(0.05)
                self._resume_info_display()  # Reactivar pantalla #2
                self._refresh_browser()

        elif btn == XboxController.L3:
            if self.mode == 'playing':
                self.player.seek(-15)

        elif btn == XboxController.R3:
            if self.mode == 'playing':
                self.player.seek(15)

        elif btn == XboxController.X:
            if self.mode == 'playing':
                self.player.set_volume(self.player.volume - VOLUME_STEP)
                self._update_info_display()

        elif btn == XboxController.Y:
            if self.mode == 'playing':
                self.player.set_volume(self.player.volume + VOLUME_STEP)
                self._update_info_display()

        elif btn in (XboxController.DPAD_U, 300):
            if self.mode == 'browser':
                if self.show_menu:
                    self.menu_idx = max(0, self.menu_idx - 1)
                else:
                    self.browser.move_up()
                    self._refresh_browser()

        elif btn in (XboxController.DPAD_D, 301):
            if self.mode == 'browser':
                if self.show_menu:
                    self.menu_idx = min(len(self.menu_items) - 1, self.menu_idx + 1)
                else:
                    self.browser.move_down()
                    self._refresh_browser()

        elif btn == XboxController.START:
            self.show_menu = True

    # ------------------------------------------------------------------
    def _play_selected(self):
        path = self.browser.get_selected_path()
        if path and os.path.exists(path):
            print(f"[App] Reproduciendo: {os.path.basename(path)}")
            # Suspender pantalla #2 para que el bus SPI sea exclusivo del video
            if self.info_disp:
                self.info_disp.suspend()
            self.player.play(path)
            self.browser.set_playing(self.browser.selected)
            self.mode = 'playing'
            self.show_menu = False

    def _exec_menu(self):
        if self.menu_idx == 0:
            self._play_selected()
        elif self.menu_idx == 1:
            self.browser.refresh()
            self._refresh_browser()
        elif self.menu_idx == 2:
            self.running = False
        self.show_menu = False

    # ------------------------------------------------------------------
    def _handle_keyboard(self, action):
        """Handle keyboard input events, mapped to same actions as Xbox buttons."""
        if action == 'QUIT':
            print("[App] Tecla Q presionada. Saliendo...")
            self.running = False
            return

        if action == 'UP':
            if self.mode == 'browser':
                if self.show_menu:
                    self.menu_idx = max(0, self.menu_idx - 1)
                else:
                    self.browser.move_up()
                    self._refresh_browser()

        elif action == 'DOWN':
            if self.mode == 'browser':
                if self.show_menu:
                    self.menu_idx = min(len(self.menu_items) - 1, self.menu_idx + 1)
                else:
                    self.browser.move_down()
                    self._refresh_browser()

        elif action == 'LEFT':
            if self.mode == 'playing':
                self.player.seek(-15)

        elif action == 'RIGHT':
            if self.mode == 'playing':
                self.player.seek(15)

        elif action == 'ENTER':
            if self.mode == 'browser':
                if self.show_menu:
                    self._exec_menu()
                else:
                    self._play_selected()
            else:
                self.player.pause()
                self._update_info_display()

        elif action == 'BACK':
            if self.mode == 'browser':
                self.show_menu = not self.show_menu
            else:
                # DETENER Y VOLVER
                print("[App] Deteniendo...")
                self.player.stop()
                self.mode = 'browser'
                _t = time.time()
                while self.player.is_playing and (time.time() - _t) < 4.0:
                    time.sleep(0.05)
                self._resume_info_display()
                self._refresh_browser()

        elif action == 'X':
            if self.mode == 'playing':
                self.player.set_volume(self.player.volume - VOLUME_STEP)
                self._update_info_display()

        elif action == 'Y':
            if self.mode == 'playing':
                self.player.set_volume(self.player.volume + VOLUME_STEP)
                self._update_info_display()

        elif action == 'L3':
            if self.mode == 'playing':
                self.player.seek(-15)

        elif action == 'R3':
            if self.mode == 'playing':
                self.player.seek(15)


if __name__ == '__main__':
    App().run()
