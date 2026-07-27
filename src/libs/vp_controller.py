"""vp_controller.py - Mando Xbox Bluetooth (restaurado, sin vp_config)."""
import os
import glob
import threading
import queue
from struct import unpack

# Deadzone para sticks analógicos (0.0-1.0)
CONTROLLER_DEADZONE = 0.3


class XboxController:
    """Maneja el mando Xbox conectado por Bluetooth.

    Botones:
        A=0, B=1, X=2, Y=3, LB=4, RB=5, SELECT=6, START=7, GUIDE=8, L3=9, R3=10
    Ejes:
        0=LX, 1=LY, 2=RX, 3=RY, 4=LT, 5=RT, 6=DPAD_X, 7=DPAD_Y
    Botones virtuales (D-Pad convertido a eventos):
        DPAD_U=300, DPAD_D=301, DPAD_L=302, DPAD_R=303
    """

    # Botones fisicos
    A = 0; B = 1; X = 2; Y = 3
    LB = 4; RB = 5; SELECT = 6; START = 7
    GUIDE = 8; L3 = 9; R3 = 10

    # Botones virtuales (D-Pad)
    DPAD_U = 300; DPAD_D = 301; DPAD_L = 302; DPAD_R = 303

    def __init__(self):
        self.connected = False
        self.js_path = None
        self.buttons = {}
        self.axes = {}
        self.event_queue = queue.Queue()
        self.running = False
        self._thread = None
        self._deadzone = CONTROLLER_DEADZONE

    def connect(self):
        """Busca y conecta el mando Xbox."""
        devices = []
        try:
            devices = sorted(glob.glob('/dev/input/js*'))
        except Exception:
            pass

        if not devices:
            for p in ['/dev/input/js0', '/dev/input/js1', '/dev/input/js2']:
                if os.path.exists(p):
                    devices.append(p)

        if not devices:
            return False

        self.js_path = devices[0]
        self.connected = True
        print(f"[Mando] ++ Conectado: {self.js_path}")
        return True

    def start(self):
        """Inicia el hilo de lectura de eventos."""
        if not self.connected:
            return False
        self.running = True
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()
        return True

    def _read_loop(self):
        """Bucle de lectura de eventos del joystick (hilo separado)."""
        try:
            with open(self.js_path, 'rb') as js:
                while self.running:
                    data = js.read(8)
                    if not data:
                        break
                    _time, value, etype, number = unpack('IhBB', data)

                    if etype == 1:  # Boton
                        self.buttons[number] = value
                        if value == 1:  # Solo prensado
                            self.event_queue.put(('btn', number))

                    elif etype == 2:  # Eje analogico
                        norm = value / 32767.0
                        self.axes[number] = norm

                        # Convertir D-Pad (ejes) a eventos de boton
                        if number == 7:  # D-Pad vertical
                            if norm < -0.5:
                                self.event_queue.put(('btn', self.DPAD_U))
                            elif norm > 0.5:
                                self.event_queue.put(('btn', self.DPAD_D))

                        if number == 6:  # D-Pad horizontal
                            if norm < -0.5:
                                self.event_queue.put(('btn', self.DPAD_L))
                            elif norm > 0.5:
                                self.event_queue.put(('btn', self.DPAD_R))

        except Exception as e:
            print(f"[Mando] Error en lectura: {e}")
        finally:
            self.running = False
            self.connected = False
            print("[Mando] -- Desconectado.")

    def get_event(self, timeout=0.01):
        """Obtiene un evento de la cola (no bloqueante)."""
        try:
            return self.event_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def stop(self):
        """Detiene el hilo de lectura."""
        self.running = False
        if self._thread:
            self._thread.join(timeout=1)
