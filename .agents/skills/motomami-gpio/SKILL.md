---
name: motomami-gpio
description: "Botones GPIO 6-direcciones + Xbox Bluetooth: digitalio, mapeo de pines, InputManager thread, event queue, debouncing."
risk: safe
source: personal
date_added: "2026-07-17"
---

# MotoMami GPIO — Botones 6-dir + Xbox

## Purpose

Guía para el sistema de entrada del MotoMami: 6 botones GPIO físicos y mando Xbox Bluetooth. Todo centralizado en `InputManager` con cola de eventos thread-safe.

## Use this when

- Modificar `src/core/input_manager.py`
- Cambiar mapeo de pines GPIO
- Añadir nuevos botones o fuentes de entrada
- Debuggear botones que no responden
- Implementar navegación en apps

## Pin Mapping

```python
GPIO_BUTTONS = {
    "UP":    13,   # GPIO13 - D13
    "DOWN":  26,   # GPIO26 - D26
    "RIGHT":  5,   # GPIO5  - D5
    "LEFT":   6,   # GPIO6  - D6
    "ENTER": 12,   # GPIO12 - D12
    "BACK":  16,   # GPIO16 - D16
}
```

**Configuración**: Pull-down (`Pull.DOWN`). Estado alto = presionado.

## API — `InputManager`

`src/core/input_manager.py`:

```python
class InputManager(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self._queue = queue.Queue(maxsize=32)
        self._gpio_pins: dict[str, digitalio.DigitalInOut] = {}
        self._xbox: XboxController | None = None
        # Estados anteriores para detectar cambios
        self._last_states: dict[str, bool] = {}

    def get_event(self, timeout=0.05) -> tuple[str, str] | None:
        """Retorna (action, source) o None.
           action: UP/DOWN/LEFT/RIGHT/ENTER/BACK/MENU/X/Y/L3/R3
           source: "gpio" | "xbox"
        """
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def run(self):
        self._init_gpio()
        self._init_xbox()
        while not self._state.shutdown_event.is_set():
            self._poll_gpio()
            self._poll_xbox()
            time.sleep(0.02)  # 50 Hz

    def stop(self):
        self._state.shutdown_event.set()
        for pin in self._gpio_pins.values():
            pin.deinit()
        if self._xbox:
            self._xbox.stop()
```

## GPIO Inicialización

```python
import board
import digitalio

def _init_gpio(self):
    for action, pin_id in GPIO_BUTTONS.items():
        pin = getattr(board, f"D{pin_id}")
        btn = digitalio.DigitalInOut(pin)
        btn.direction = digitalio.Direction.INPUT
        btn.pull = digitalio.Pull.DOWN
        self._gpio_pins[action] = btn
        self._last_states[action] = btn.value
```

## Polling con Debounce

```python
def _poll_gpio(self):
    for action, btn in self._gpio_pins.items():
        current = btn.value
        last = self._last_states[action]
        if current and not last:  # rising edge = press
            self._push(action, "gpio")
        self._last_states[action] = current
```

**Nota**: No hay debounce por software explícito. La tasa de 50 Hz y `Pull.DOWN` son suficientes para botones mecánicos típicos. Si hay rebote, añadir:

```python
if current and not last:
    time.sleep(0.01)  # debounce 10ms
    if btn.value:  # confirmar
        self._push(action, "gpio")
```

## Xbox Bluetooth

```python
def _init_xbox(self):
    try:
        from libs.vp_controller import XboxController
        self._xbox = XboxController()
        self._xbox.start()
    except Exception:
        self._xbox = None  # Xbox no disponible, solo GPIO

def _poll_xbox(self):
    if not self._xbox:
        return
    for event in self._xbox.get_events():
        action = self._xbox_btn_to_action(event)
        if action:
            self._push(action, "xbox")

def _xbox_btn_to_action(self, btn_code):
    mapping = {
        0: "UP", 1: "DOWN", 2: "LEFT", 3: "RIGHT",
        4: "ENTER", 5: "BACK", 6: "MENU", 7: "X", 8: "Y",
    }
    return mapping.get(btn_code)
```

## Patrón de Uso en Apps

```python
class MyApp:
    def __init__(self, input_mgr: InputManager, ...):
        self._input = input_mgr
        self._running = True

    def run(self):
        self._render()
        while self._running:
            evt = self._input.get_event(timeout=0.05)
            if evt:
                action, source = evt
                if action == "UP":
                    self._menu_idx = max(0, self._menu_idx - 1)
                    self._render()
                elif action == "DOWN":
                    self._menu_idx = min(len(self._items)-1, self._menu_idx + 1)
                    self._render()
                elif action == "ENTER":
                    self._select_item()
                elif action == "BACK":
                    self._running = False
```

## Debugging

```bash
# Probar GPIO con raspi-gpio
raspi-gpio get 13
raspi-gpio get 26

# Ver todos los pines
raspi-gpio get

# Probar bluetooth Xbox
sudo bluetoothctl
# scan on
# trust <MAC>
# connect <MAC>

# Ver eventos de entrada (funciona si está configurado como input device)
sudo evtest
```

**Problemas comunes**:  
- Botón no detectado → `Pull.DOWN` vs `Pull.UP` incorrecto, verificar硬件
- Múltiples disparos → añadir debounce de 10ms
- Xbox no conecta → `bluetoothctl` pair/trust manual primero
- `board.D13` no existe → usar `getattr(board, f"D{pin_id}")`
- `digitalio` falla → ejecutar con `sudo` (requiere acceso a /dev/gpiomem)

## Key Files

| File | Role |
|------|------|
| `src/core/input_manager.py` | InputManager centralizado (GPIO + Xbox) |
| `src/main.py` | Creación y arranque del InputManager |
| `final/src/apps/*.py` | Legacy: GPIO directo en cada app |
| `.agents/rules/pinout-rpi.md` | Pinout de referencia |
