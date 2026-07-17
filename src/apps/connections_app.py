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


class ConnectionsApp:
    def __init__(self, input_mgr, state=None):
        self._input = input_mgr
        self._state = state
        self._fb = FbDisplay(3)
        self._running = False
        self._screen = "main"
        self._menu_idx = 0
        self._refresh_thread = None

    def run(self):
        self._running = True
        self._draw_main()
        while self._running:
            evt = self._input.get_event(timeout=0.1)
            if evt:
                action, _ = evt
                if self._screen == "main":
                    self._handle_main(action)
                elif self._screen == "usb":
                    if action == "BACK":
                        self._screen = "main"
                        self._draw_main()
                    elif action == "ENTER":
                        self._refresh_usb()
                elif self._screen == "wifi":
                    if action == "BACK":
                        self._screen = "main"
                        self._draw_main()
                    elif action == "ENTER":
                        self._refresh_wifi()
                elif self._screen == "bt":
                    if action == "BACK":
                        self._screen = "main"
                        self._draw_main()
                    elif action == "ENTER":
                        self._refresh_bt()

        self._fb.blank()
        self._fb.update()

    def _handle_main(self, action):
        items = ["USB Devices", "WiFi Status", "Bluetooth"]
        if action == "UP":
            self._menu_idx = max(0, self._menu_idx - 1)
            self._draw_main()
        elif action == "DOWN":
            self._menu_idx = min(len(items) - 1, self._menu_idx + 1)
            self._draw_main()
        elif action == "ENTER":
            if self._menu_idx == 0:
                self._screen = "usb"
                self._refresh_usb()
            elif self._menu_idx == 1:
                self._screen = "wifi"
                self._refresh_wifi()
            elif self._menu_idx == 2:
                self._screen = "bt"
                self._refresh_bt()
        elif action == "BACK":
            self._running = False

    def _draw_main(self):
        items = ["> USB Devices", "  WiFi Status", "  Bluetooth"]
        self._fb.blank()
        d = self._fb.draw()
        d.rectangle([(0, 0), (319, 27)], fill=(0, 20, 60))
        d.text((8, 4), "CONEXIONES", font=self._fb.font_title, fill=(80, 180, 255))
        y = 40
        for i, item in enumerate(items):
            color = (80, 180, 255) if i == self._menu_idx else (120, 120, 120)
            if i == self._menu_idx:
                d.rectangle([(2, y - 2), (317, y + 20)], fill=(0, 20, 50), outline=(80, 180, 255))
            d.text((12, y + 2), item, font=self._fb.font, fill=color)
            y += 32

        ox = 321
        d.rectangle([(ox + 4, 4), (ox + 315, 235)], outline=(80, 180, 255), width=2)
        d.text((ox + 10, 10), "CONEXIONES", font=self._fb.font_title, fill=(80, 180, 255))
        d.text((ox + 10, 50), "Muestra el estado", font=self._fb.font, fill=(180, 180, 180))
        d.text((ox + 10, 72), "de los dispositivos", font=self._fb.font, fill=(180, 180, 180))
        d.text((ox + 10, 94), "conectados al sistema", font=self._fb.font, fill=(180, 180, 180))
        d.text((ox + 10, 130), "ENTER = Refrescar", font=self._fb.font_s, fill=(100, 150, 200))
        d.text((ox + 10, 150), "BACK = Volver", font=self._fb.font_s, fill=(100, 150, 200))
        self._fb.update()

    def _run_cmd(self, cmd, timeout=5):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return r.stdout + r.stderr
        except Exception as e:
            return f"Error: {e}"

    def _refresh_usb(self):
        lines = ["=== DISPOSITIVOS USB ===", ""]
        lsusb = self._run_cmd(["lsusb"], timeout=3)
        lines.append(lsusb.strip() or "(ninguno)")
        lines.append("")
        tty = self._run_cmd(["ls", "-la", "/dev/ttyUSB*"], timeout=2)
        if tty.strip():
            lines.append("Puertos serie:")
            for ln in tty.splitlines():
                parts = ln.split()
                if len(parts) >= 10:
                    lines.append(f"  {parts[-1]}")
        else:
            lines.append("Puertos serie: (ninguno)")
        lines.append("")
        lines.append("ENTER=Refrescar  BACK=Volver")
        self._draw_result(lines, "USB", (100, 255, 100))

    def _refresh_wifi(self):
        lines = ["=== WIFI ===", ""]
        iwconfig = self._run_cmd(["iwconfig"], timeout=3)
        if "no wireless" in iwconfig.lower() or not iwconfig.strip():
            lines.append("(Sin interfaz WiFi o desconectado)")
        else:
            for ln in iwconfig.splitlines():
                if ln.strip():
                    lines.append(ln.strip()[:60])
        lines.append("")
        ip_a = self._run_cmd(["ip", "-4", "addr", "show"], timeout=2)
        lines.append("Direcciones IP:")
        for ln in ip_a.splitlines():
            if "inet " in ln:
                parts = ln.strip().split()
                if len(parts) >= 2:
                    iface = ln.split(":")[0].strip() if ":" in ln else ""
                    lines.append(f"  {parts[-1]}: {parts[1]}")
        lines.append("")
        ping = self._run_cmd(["ping", "-c1", "-W2", "8.8.8.8"], timeout=3)
        if "1 received" in ping or "1 packets received" in ping:
            lines.append("Internet: CONECTADO")
        else:
            lines.append("Internet: SIN CONEXION")
        lines.append("")
        lines.append("ENTER=Refrescar  BACK=Volver")
        self._draw_result(lines, "WIFI", (255, 200, 100))

    def _refresh_bt(self):
        lines = ["=== BLUETOOTH ===", ""]
        bt_stat = self._run_cmd(["systemctl", "is-active", "bluetooth"], timeout=2)
        lines.append(f"Servicio: {bt_stat.strip()}")
        lines.append("")
        devs = self._run_cmd(["bluetoothctl", "devices"], timeout=5)
        if devs.strip():
            paired = [ln for ln in devs.splitlines() if "Device" in ln]
            lines.append(f"Dispositivos emparejados: {len(paired)}")
            for p in paired[:6]:
                lines.append(f"  {p[20:50]}")
        else:
            lines.append("Sin dispositivos emparejados")
        lines.append("")
        info = self._run_cmd(["bluetoothctl", "show"], timeout=4)
        for ln in info.splitlines():
            if "Powered" in ln or "Discovering" in ln or "Pairable" in ln:
                lines.append(ln.strip()[:55])
        lines.append("")
        lines.append("ENTER=Refrescar  BACK=Volver")
        self._draw_result(lines, "BLUETOOTH", (100, 200, 255))

    def _draw_result(self, lines, title, color):
        self._fb.blank()
        d = self._fb.draw()
        d.rectangle([(0, 0), (639, 27)], fill=(0, 20, 50))
        d.text((8, 4), title, font=self._fb.font_title, fill=color)
        y = 32
        for line in lines:
            c = color
            if "Error" in line or "SIN CONEXION" in line or "ninguno" in line.lower():
                c = (255, 100, 100)
            elif "CONECTADO" in line or "OK" in line or "active" in line.lower():
                c = (100, 255, 100)
            d.text((5, y), str(line)[:62], font=self._fb.font_s, fill=c)
            y += 12
            if y > 230:
                break
        self._fb.update()
