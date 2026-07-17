import os
import sys
import time
import subprocess
import threading

_SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from libs.fb_display import FbDisplay, _find_font
from PIL import Image, ImageDraw


class BluetoothManagerApp:
    def __init__(self, input_mgr, state=None):
        self._input = input_mgr
        self._state = state
        self._fb = FbDisplay(3)
        self._running = False
        self._screen = "main"
        self._menu_idx = 0
        self._paired = []
        self._discovered = []
        self._scanning = False

    def run(self):
        self._running = True
        self._load_paired()
        self._draw_main()
        while self._running:
            evt = self._input.get_event(timeout=0.1)
            if evt:
                action, _ = evt
                if self._screen == "main":
                    self._handle_main(action)
                elif self._screen == "paired":
                    self._handle_paired(action)
                elif self._screen == "scan":
                    self._handle_scan(action)
                elif self._screen == "info":
                    if action == "BACK":
                        self._screen = "main"
                        self._draw_main()

        self._fb.blank()
        self._fb.update()

    def _handle_main(self, action):
        items = ["Ver emparejados", "Escanear dispositivos", "Ayuda Bluetooth"]
        if action == "UP":
            self._menu_idx = max(0, self._menu_idx - 1)
            self._draw_main()
        elif action == "DOWN":
            self._menu_idx = min(len(items) - 1, self._menu_idx + 1)
            self._draw_main()
        elif action == "ENTER":
            if self._menu_idx == 0:
                self._screen = "paired"
                self._draw_paired()
            elif self._menu_idx == 1:
                self._screen = "scan"
                self._start_scan()
            elif self._menu_idx == 2:
                self._screen = "info"
                self._draw_help()
        elif action == "BACK":
            self._running = False

    def _draw_main(self):
        items = ["> Ver emparejados", "  Escanear dispositivos", "  Ayuda Bluetooth"]
        self._fb.blank()
        d = self._fb.draw()
        d.rectangle([(0, 0), (319, 27)], fill=(40, 0, 80))
        d.text((8, 4), "BLUETOOTH", font=self._fb.font_title, fill=(180, 80, 255))
        y = 40
        for i, item in enumerate(items):
            color = (180, 80, 255) if i == self._menu_idx else (120, 120, 120)
            if i == self._menu_idx:
                d.rectangle([(2, y - 2), (317, y + 20)], fill=(30, 0, 60), outline=(180, 80, 255))
            d.text((12, y + 2), item, font=self._fb.font, fill=color)
            y += 32

        ox = 321
        d.rectangle([(ox + 4, 4), (ox + 315, 235)], outline=(180, 80, 255), width=2)
        d.text((ox + 10, 10), "BLUETOOTH", font=self._fb.font_title, fill=(180, 80, 255))
        d.text((ox + 10, 50), "Gestiona dispositivos", font=self._fb.font, fill=(180, 180, 180))
        d.text((ox + 10, 72), "Bluetooth:", font=self._fb.font, fill=(180, 180, 180))
        d.text((ox + 10, 105), "- Xbox controller", font=self._fb.font_s, fill=(150, 150, 200))
        d.text((ox + 10, 125), "- Audifonos BT", font=self._fb.font_s, fill=(150, 150, 200))
        d.text((ox + 10, 145), "- Teclado / mouse", font=self._fb.font_s, fill=(150, 150, 200))
        d.text((ox + 10, 185), f"Emparejados: {len(self._paired)}", font=self._fb.font, fill=(180, 80, 255))
        self._fb.update()

    def _run_cmd(self, cmd, timeout=8):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return r.stdout + r.stderr
        except Exception as e:
            return f""

    def _load_paired(self):
        out = self._run_cmd(["bluetoothctl", "devices"], timeout=5)
        self._paired = [ln for ln in out.splitlines() if "Device" in ln] if out else []

    def _draw_paired(self):
        lines = []
        lines.append(f"=== EMPAREJADOS: {len(self._paired)} ===")
        lines.append("")

        if self._paired:
            for i, dev in enumerate(self._paired):
                dev_clean = dev.replace("Device ", "").strip()
                mac = dev_clean[:17]
                name = dev_clean[18:].strip()
                connected = self._is_connected(mac)
                icon = ">>" if connected else "  "
                lines.append(f"{icon} {name or '(sin nombre)'}")
                lines.append(f"   {mac}")
                lines.append("")
        else:
            lines.append("(Sin dispositivos emparejados)")
            lines.append("")
            lines.append("Selecciona 'Escanear' para")
            lines.append("buscar y emparejar nuevos.")

        lines.append("ENTER=Actualizar  BACK=Volver")
        self._draw_result(lines, "DISPOSITIVOS BT", (180, 80, 255))

    def _handle_paired(self, action):
        if action == "ENTER":
            self._load_paired()
            self._draw_paired()
        elif action == "BACK":
            self._screen = "main"
            self._draw_main()

    def _is_connected(self, mac):
        out = self._run_cmd(["bluetoothctl", "info", mac], timeout=4)
        return "Connected: yes" in out

    def _start_scan(self):
        self._scanning = True
        self._draw_result(["ESCANEANDO...", "", "Buscando dispositivos BT...", "", "Espera 10 segundos..."], "ESCANEO", (100, 200, 255))

        def scan_worker():
            subprocess.run(["bluetoothctl", "--timeout", "10", "scan", "on"], capture_output=True, text=True, timeout=12)
            out = self._run_cmd(["bluetoothctl", "devices"], timeout=5)
            all_devs = [ln for ln in out.splitlines() if "Device" in ln] if out else []
            new_devs = [d for d in all_devs if d not in self._paired]
            self._discovered = new_devs
            self._scanning = False

            lines = []
            lines.append(f"=== DISPOSITIVOS ENCONTRADOS ===")
            lines.append(f"  Nuevos: {len(new_devs)}")
            lines.append(f"  Total disponibles: {len(all_devs)}")
            lines.append("")

            if new_devs:
                lines.append("NUEVOS:")
                for i, dev in enumerate(new_devs[:8]):
                    clean = dev.replace("Device ", "").strip()
                    parts = clean.split(" ", 1)
                    mac = parts[0]
                    name = parts[1] if len(parts) > 1 else ""
                    lines.append(f"  [{i+1}] {name or '(sin nombre)'}")
                    lines.append(f"      {mac}")
                    lines.append("")
            else:
                lines.append("(Sin dispositivos nuevos)")
                lines.append("")
                lines.append("Asegura que el dispositivo")
                lines.append("esté en modo pairing.")

            lines.append("")
            lines.append("Para emparejar:")
            lines.append("1. Anota la direccion MAC")
            lines.append("2. Usa en terminal:")
            lines.append("   bluetoothctl pair <MAC>")
            lines.append("   bluetoothctl trust <MAC>")
            lines.append("   bluetoothctl connect <MAC>")
            lines.append("")
            lines.append("ENTER=Escanear de nuevo")
            lines.append("BACK=Volver")

            self._draw_result(lines, "ESCANEO", (100, 200, 255))

        t = threading.Thread(target=scan_worker, daemon=True)
        t.start()

    def _handle_scan(self, action):
        if action == "ENTER":
            self._start_scan()
        elif action == "BACK":
            self._screen = "main"
            self._draw_main()

    def _draw_help(self):
        lines = [
            "=== AYUDA BLUETOOTH ===",
            "",
            "Emparejar Xbox Controller:",
            "1. Pon el mando en pairing",
            "   (Boton Xbox + boton pairing)",
            "2. Escanea desde esta app",
            "3. En terminal:",
            "   bluetoothctl pair <MAC>",
            "   bluetoothctl trust <MAC>",
            "   bluetoothctl connect <MAC>",
            "",
            "Audifonos BT:",
            "1. Ponlos en pairing mode",
            "2. Escanea y conecta",
            "3. Configura audio en:",
            "   sudo raspi-config",
            "",
            "Xbox ya conectado antes?",
            "Se conecta automaticamente",
            "al encender el mando.",
            "",
            "BACK para volver",
        ]
        self._draw_result(lines, "AYUDA BT", (200, 200, 100))

    def _draw_result(self, lines, title, color):
        self._fb.blank()
        d = self._fb.draw()
        d.rectangle([(0, 0), (639, 27)], fill=(30, 0, 60))
        d.text((8, 4), title, font=self._fb.font_title, fill=color)
        y = 32
        for line in lines:
            c = color
            if "Error" in line or "Sin" in line:
                c = (255, 100, 100)
            elif ">>" in str(line):
                c = (100, 255, 100)
            elif "[" in str(line) and "]" in str(line):
                c = (180, 180, 100)
            d.text((5, y), str(line)[:62], font=self._fb.font_s, fill=c)
            y += 12
            if y > 230:
                break
        self._fb.update()
