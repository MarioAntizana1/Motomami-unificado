"""
input_manager.py - Gestor unificado de entradas (Xbox + GPIO).
Produce eventos a través de una cola thread-safe.
"""
import threading
import queue
import time
import os
import sys

# ── Botones GPIO ──
GPIO_BUTTONS = {
    "UP":    13,
    "DOWN":  26,
    "RIGHT":  5,
    "LEFT":   6,
    "ENTER": 12,
    "BACK":  16,
}

try:
    import board
    import digitalio
    _HAS_GPIO = True
except (ImportError, NotImplementedError):
    _HAS_GPIO = False


class InputManager(threading.Thread):
    """
    Lee GPIO y mando Xbox, publica eventos a una cola.
    Uso:
        im = InputManager()
        im.start()
        event = im.get_event(timeout=0.05)  # ("UP", "btn"), etc.
    """

    def __init__(self):
        super().__init__(name="InputManager", daemon=True)
        self._queue: queue.Queue = queue.Queue(maxsize=32)
        self._stop_event = threading.Event()
        self._btns = {}
        self._btn_prev = {}
        self._btn_candidate = {}
        self._btn_candidate_since = {}
        self._xbox = None

        # Intentar Xbox
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "libs"))
        try:
            from vp_controller import XboxController
            self._xbox_cls = XboxController
        except ImportError:
            self._xbox_cls = None

    def _init_gpio(self):
        if not _HAS_GPIO:
            return
        for name, gpio_num in GPIO_BUTTONS.items():
            try:
                pin = getattr(board, f"D{gpio_num}")
                btn = digitalio.DigitalInOut(pin)
                btn.direction = digitalio.Direction.INPUT
                btn.pull = digitalio.Pull.DOWN
                current = bool(btn.value)
                self._btns[name] = btn
                self._btn_prev[name] = current
                self._btn_candidate[name] = current
                self._btn_candidate_since[name] = time.monotonic()
            except Exception as e:
                print(f"[Input] GPIO{gpio_num} ({name}): {e}")

    def _init_xbox(self):
        if not self._xbox_cls:
            return
        try:
            xbox = self._xbox_cls()
            if xbox.connect():
                xbox.start()
                self._xbox = xbox
                print("[Input] Mando Xbox conectado")
            else:
                self._xbox = None
        except Exception as e:
            self._xbox = None
            print(f"[Input] Error Xbox: {e}")

    def _push(self, action: str, source: str = "gpio"):
        """Añade evento a la cola sin bloquear."""
        try:
            self._queue.put_nowait((action, source))
        except queue.Full:
            pass  # Descartar si la cola está llena

    def get_event(self, timeout: float = 0.02):
        """
        Obtiene el siguiente evento de entrada.
        Retorna (action, source) o None si no hay evento.
        action: "UP" | "DOWN" | "LEFT" | "RIGHT" | "ENTER" | "BACK"
        source: "gpio" | "xbox"
        """
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    XBOX_RETRY_INTERVAL = 3.0  # segundos entre reintentos de conexión

    def run(self):
        self._init_gpio()
        self._init_xbox()
        print(f"[Input] GPIO={'OK' if self._btns else 'N/A'} Xbox={'OK' if self._xbox else 'N/A'}")
        last_xbox_retry = time.time()

        while not self._stop_event.is_set():
            # ── Leer GPIO ──
            now = time.monotonic()
            for name, btn in self._btns.items():
                try:
                    cur = bool(btn.value)
                except Exception:
                    cur = False

                stable = self._btn_prev.get(name, False)
                candidate = self._btn_candidate.get(name, stable)
                if cur == stable:
                    self._btn_candidate[name] = cur
                    self._btn_candidate_since[name] = now
                    continue
                if cur != candidate:
                    self._btn_candidate[name] = cur
                    self._btn_candidate_since[name] = now
                    continue
                if now - self._btn_candidate_since.get(name, now) >= 0.04:
                    self._btn_prev[name] = cur
                    if cur:
                        self._push(name, "gpio")

            # ── Xbox: hot-plug / reconexión ──
            if self._xbox is None or not self._xbox.connected:
                if self._xbox is not None:
                    # Se desconectó: limpiar y reintentar
                    try:
                        self._xbox.stop()
                    except Exception:
                        pass
                    self._xbox = None
                    print("[Input] Xbox desconectado, reintentando...")
                now = time.time()
                if now - last_xbox_retry >= self.XBOX_RETRY_INTERVAL:
                    last_xbox_retry = now
                    self._init_xbox()
            else:
                # ── Leer Xbox ──
                try:
                    evt = self._xbox.get_event(0.005)
                    while evt:
                        if evt[0] == "btn":
                            action = self._xbox_btn_to_action(evt[1])
                            if action:
                                self._push(action, "xbox")
                        evt = self._xbox.get_event(0.001)
                except Exception as e:
                    print(f"[Input] Error Xbox read: {e}")

            time.sleep(0.02)  # 50 Hz polling

    def _xbox_btn_to_action(self, btn_code) -> str:
        """Convierte código de botón Xbox a acción."""
        if not self._xbox:
            return None
        X = self._xbox_cls
        mapping = {
            X.DPAD_U: "UP",
            300: "UP",
            X.DPAD_D: "DOWN",
            301: "DOWN",
            X.DPAD_L: "LEFT",
            302: "LEFT",
            X.DPAD_R: "RIGHT",
            303: "RIGHT",
            X.A: "ENTER",
            X.B: "BACK",
            X.START: "MENU",
            X.X: "X",
            X.Y: "Y",
            X.L3: "L3",
            X.R3: "R3",
        }
        return mapping.get(btn_code)

    def stop(self):
        self._stop_event.set()
        if self._xbox:
            try:
                self._xbox.stop()
            except Exception:
                pass
        for btn in self._btns.values():
            try:
                btn.deinit()
            except Exception:
                pass
        print("[Input] Detenido.")
