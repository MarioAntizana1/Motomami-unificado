import os
import sys
import time
import subprocess
import threading
import re

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
        self._dev_idx = 0
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
                elif self._screen == "dev_detail":
                    self._handle_dev_detail(action)
                elif self._screen == "scan":
                    self._handle_scan(action)
                elif self._screen == "scan_dev":
                    self._handle_scan_dev(action)
                elif self._screen == "audio_out":
                    self._handle_audio_out(action)
                elif self._screen == "result":
                    if action == "ENTER" or action == "BACK":
                        self._screen = "main"
                        self._draw_main()

        self._fb.blank()
        self._fb.update()

    def _handle_main(self, action):
        items = ["Ver emparejados", "Escanear dispositivos", "Salida de audio", "Ayuda Bluetooth"]
        if action == "UP":
            self._menu_idx = max(0, self._menu_idx - 1)
            self._draw_main()
        elif action == "DOWN":
            self._menu_idx = min(len(items) - 1, self._menu_idx + 1)
            self._draw_main()
        elif action == "ENTER":
            if self._menu_idx == 0:
                self._screen = "paired"
                self._dev_idx = 0
                self._draw_paired()
            elif self._menu_idx == 1:
                self._screen = "scan"
                self._start_scan()
            elif self._menu_idx == 2:
                self._screen = "audio_out"
                self._dev_idx = 0
                self._draw_audio_out()
            elif self._menu_idx == 3:
                self._screen = "result"
                self._draw_help()
        elif action == "BACK":
            self._running = False

    def _draw_main(self):
        items = ["> Ver emparejados", "  Escanear dispositivos", "  Salida de audio", "  Ayuda Bluetooth"]
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
            y += 28

        ox = 321
        d.rectangle([(ox + 4, 4), (ox + 315, 235)], outline=(180, 80, 255), width=2)
        d.text((ox + 10, 10), "BLUETOOTH", font=self._fb.font_title, fill=(180, 80, 255))
        d.text((ox + 10, 50), "Gestiona dispositivos", font=self._fb.font, fill=(180, 180, 180))
        d.text((ox + 10, 70), "Bluetooth:", font=self._fb.font, fill=(180, 180, 180))
        d.text((ox + 10, 100), "- Xbox controller", font=self._fb.font_s, fill=(150, 150, 200))
        d.text((ox + 10, 118), "- Audifonos BT", font=self._fb.font_s, fill=(150, 150, 200))
        d.text((ox + 10, 136), "- Teclado / mouse", font=self._fb.font_s, fill=(150, 150, 200))
        d.text((ox + 10, 170), f"Emparejados: {len(self._paired)}", font=self._fb.font, fill=(180, 80, 255))
        current = self._get_current_sink_name()
        d.text((ox + 10, 200), f"Audio: {current}", font=self._fb.font_s, fill=(100, 200, 100))
        self._fb.update()

    def _run_cmd(self, cmd, timeout=10):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return r.stdout + r.stderr
        except Exception:
            return ""

    def _btctl(self, cmd_str, timeout=8):
        return self._run_cmd(["bluetoothctl"] + cmd_str.split(), timeout=timeout)

    def _load_paired(self):
        out = self._btctl("devices", timeout=5)
        self._paired = [ln for ln in out.splitlines() if "Device" in ln] if out else []

    def _parse_devices(self, lines):
        devs = []
        for ln in lines:
            if "Device" not in ln:
                continue
            clean = ln.replace("Device ", "").strip()
            mac = clean[:17]
            name = clean[18:].strip()
            devs.append({"mac": mac, "name": name or "(sin nombre)"})
        return devs

    def _is_connected(self, mac):
        out = self._btctl(f"info {mac}", timeout=4)
        return "Connected: yes" in out

    def _get_device_class(self, mac):
        out = self._btctl(f"info {mac}", timeout=4)
        if "Icon:" in out:
            for ln in out.splitlines():
                if "Icon:" in ln:
                    icon = ln.split("Icon:")[-1].strip()
                    if "audio" in icon.lower() or "headset" in icon.lower() or "speaker" in icon.lower():
                        return "audio"
                    if "input" in icon.lower() or "game" in icon.lower() or "joystick" in icon.lower():
                        return "input"
        return "unknown"

    def _get_current_sink_name(self):
        out = self._run_cmd(["pactl", "get-default-sink"], timeout=3)
        name = out.strip()
        if "bluez" in name.lower() or "blue" in name.lower():
            return "BT audifonos"
        if "fiio" in name.lower() or "dac" in name.lower():
            return "Fiio DAC"
        if "headphone" in name.lower() or "bcm" in name.lower() or "analog" in name.lower():
            return "Jack 3.5mm"
        return name[:14] if name else "default"

    def _list_sinks(self):
        out = self._run_cmd(["pactl", "list", "sinks", "short"], timeout=3)
        sinks = []
        for ln in out.splitlines():
            parts = ln.strip().split()
            if len(parts) >= 2:
                sinks.append({"id": parts[0], "name": parts[1]})
        return sinks

    def _set_default_sink(self, name):
        self._run_cmd(["pactl", "set-default-sink", name], timeout=3)

    def _get_audio_ports(self, mac):
        out = self._btctl(f"info {mac}", timeout=4)
        ports = []
        for ln in out.splitlines():
            if "UUID" in ln and ("Audio" in ln or "a2dp" in ln.lower() or "headset" in ln.lower()):
                ports.append(ln.strip()[:55])
        return ports

    # ── Paired devices screen ──

    def _draw_paired(self):
        self._load_paired()
        lines = []
        lines.append(f"=== EMPAREJADOS: {len(self._paired)} ===")
        lines.append("")
        if self._paired:
            devs = self._parse_devices(self._paired)
            for i, d in enumerate(devs):
                connected = self._is_connected(d["mac"])
                sel = ">" if i == self._dev_idx else " "
                icon = ">>" if connected else "  "
                lines.append(f"{sel} {icon} {d['name']}")
                lines.append(f"   {d['mac']}")
                lines.append("")
        else:
            lines.append("(Sin dispositivos emparejados)")
            lines.append("")
            lines.append("Escanea y empareja uno")
            lines.append("desde 'Escanear' en el menu.")
        lines.append("ENTER=Detalle  BACK=Volver  ^v=Navegar")
        self._draw_result(lines, "EMPAREJADOS", (180, 80, 255), highlight=self._dev_idx if self._paired else -1)

    def _handle_paired(self, action):
        if action == "UP":
            self._dev_idx = max(0, self._dev_idx - 1)
            self._draw_paired()
        elif action == "DOWN":
            self._dev_idx = min(len(self._paired) - 1, self._dev_idx + 1)
            self._draw_paired()
        elif action == "ENTER":
            if self._paired:
                self._screen = "dev_detail"
                self._draw_dev_detail()
        elif action == "BACK":
            self._screen = "main"
            self._draw_main()

    # ── Device detail screen ──

    def _draw_dev_detail(self):
        devs = self._parse_devices(self._paired)
        if not devs or self._dev_idx >= len(devs):
            self._screen = "paired"
            self._draw_paired()
            return
        d = devs[self._dev_idx]
        mac = d["mac"]
        connected = self._is_connected(mac)
        dev_class = self._get_device_class(mac)
        audio_ports = self._get_audio_ports(mac)
        current_sink = self._run_cmd(["pactl", "get-default-sink"], timeout=2).strip()

        lines = []
        lines.append(f"=== {d['name']} ===")
        lines.append(f"")
        lines.append(f"MAC: {mac}")
        lines.append(f"Tipo: {dev_class}")
        lines.append(f"Estado: {'CONECTADO' if connected else 'DESCONECTADO'}")
        lines.append("")
        if audio_ports:
            lines.append("Perfiles audio:")
            for p in audio_ports:
                lines.append(f"  {p}")
        is_bt_sink = False
        sinks = self._list_sinks()
        for s in sinks:
            if mac.replace(":", "_") in s["name"] or d["name"].lower().replace(" ", "_") in s["name"]:
                is_bt_sink = True
                break
        lines.append("")
        lines.append("Acciones:")
        if connected:
            lines.append("[E] Desconectar")
            if dev_class == "audio" or is_bt_sink or audio_ports:
                if is_bt_sink and current_sink and mac.replace(":", "_") in current_sink:
                    lines.append("[A] Audio: ACTIVO ahora")
                else:
                    lines.append("[A] Usar como salida audio")
        else:
            lines.append("[E] Conectar")
        lines.append("")
        lines.append("[ENTER] Accion  BACK=Volver")
        self._dev_detail_mac = mac
        self._dev_detail_class = dev_class
        self._dev_detail_bt_sink = is_bt_sink
        self._draw_result(lines, "DETALLE", (180, 200, 255))

    _dev_detail_mac = ""
    _dev_detail_class = "unknown"
    _dev_detail_bt_sink = False

    def _handle_dev_detail(self, action):
        if action == "ENTER":
            mac = self._dev_detail_mac
            connected = self._is_connected(mac)
            dev_class = self._dev_detail_class
            is_bt_sink = self._dev_detail_bt_sink

            if connected:
                self._screen = "result"
                self._btctl(f"disconnect {mac}", timeout=5)
                self._show_result(f"Desconectado:\n{mac}")
                self._load_paired()
            else:
                self._screen = "result"
                out = self._btctl(f"connect {mac}", timeout=12)
                if "Connection successful" in out or "Connected: yes" in out:
                    self._show_result(f"Conectado!\n{mac}")
                    if dev_class == "audio" or is_bt_sink:
                        time.sleep(1)
                        sinks = self._list_sinks()
                        for s in sinks:
                            if mac.replace(":", "_") in s["name"]:
                                self._set_default_sink(s["name"])
                                self._show_result(f"Conectado + Audio\ncambiado a {s['name'][:20]}")
                                break
                else:
                    err = out.replace("\n", " ")[:60]
                    self._show_result(f"Fallo conexion:\n{err}")
                self._load_paired()
        elif action == "A":
            mac = self._dev_detail_mac
            sinks = self._list_sinks()
            found = False
            for s in sinks:
                if mac.replace(":", "_") in s["name"]:
                    self._set_default_sink(s["name"])
                    self._screen = "result"
                    self._show_result(f"Audio cambiado a:\n{s['name'][:20]}")
                    found = True
                    break
            if not found:
                self._screen = "result"
                self._show_result(f"No se encontro sink\nBT para {mac}\n\nConectalo primero")
        elif action == "BACK":
            self._screen = "paired"
            self._draw_paired()

    # ── Scan screen ──

    def _start_scan(self):
        self._scanning = True
        lines = ["ESCANEANDO...", "", "Buscando dispositivos BT...", "", "Espera 10 segundos..."]
        self._draw_result(lines, "ESCANEO", (100, 200, 255))

        def scan_worker():
            subprocess.run(["bluetoothctl", "--timeout", "10", "scan", "on"], capture_output=True, text=True, timeout=12)
            out = self._btctl("devices", timeout=5)
            all_devs = self._parse_devices(out.splitlines()) if out else []
            paired_macs = {d["mac"] for d in self._parse_devices(self._paired)}
            self._discovered = [d for d in all_devs if d["mac"] not in paired_macs]
            self._scanning = False

            lines = []
            lines.append(f"=== DISPOSITIVOS ENCONTRADOS ===")
            lines.append(f"  Nuevos: {len(self._discovered)}")
            lines.append(f"  Total: {len(all_devs)}")
            lines.append("")
            if self._discovered:
                for i, d in enumerate(self._discovered[:8]):
                    lines.append(f"  [{i + 1}] {d['name']}")
                    lines.append(f"      {d['mac']}")
                    lines.append("")
            else:
                lines.append("(Sin dispositivos nuevos)")
                lines.append("")
                lines.append("Asegura que el dispositivo")
                lines.append("este en modo pairing.")
            lines.append("")
            lines.append("ENTER=Seleccionar  BACK=Volver")
            self._dev_idx = 0
            self._draw_result(lines, "ESCANEO", (100, 200, 255), highlight=0 if self._discovered else -1)

        t = threading.Thread(target=scan_worker, daemon=True)
        t.start()

    def _handle_scan(self, action):
        if action == "ENTER":
            if self._discovered:
                self._screen = "scan_dev"
                self._draw_scan_dev()
        elif action == "BACK":
            self._screen = "main"
            self._draw_main()

    def _draw_scan_dev(self):
        if not self._discovered:
            self._screen = "scan"
            self._start_scan()
            return
        d = self._discovered[0]
        lines = []
        lines.append(f"=== NUEVO DISPOSITIVO ===")
        lines.append("")
        lines.append(f"Nombre: {d['name']}")
        lines.append(f"MAC: {d['mac']}")
        lines.append("")
        lines.append("Acciones:")
        lines.append("[E] Emparejar + Conectar")
        lines.append("[A] Emparejar + Conectar")
        lines.append("    y usar como audio")
        lines.append("")
        lines.append("[ENTER] Emparejar")
        lines.append("[A] Emparejar + audio")
        lines.append("[BACK] Volver")
        self._discovered_mac = d["mac"]
        self._discovered_name = d["name"]
        self._draw_result(lines, "NUEVO", (100, 200, 255))

    _discovered_mac = ""
    _discovered_name = ""

    def _handle_scan_dev(self, action):
        mac = self._discovered_mac
        if action == "ENTER":
            self._screen = "result"
            self._show_result(f"Emparejando con\n{mac}...")
            out1 = self._btctl(f"pair {mac}", timeout=15)
            out2 = self._btctl(f"trust {mac}", timeout=5)
            out3 = self._btctl(f"connect {mac}", timeout=12)
            if "Connection successful" in out3 or "Connected: yes" in out3:
                self._show_result(f"Emparejado + Conectado!\n{mac}")
            else:
                self._show_result(f"Emparejado\n(checkear conexion)")
            self._load_paired()
        elif action == "A":
            self._screen = "result"
            self._show_result(f"Emparejando + audio...")
            self._btctl(f"pair {mac}", timeout=15)
            self._btctl(f"trust {mac}", timeout=5)
            out = self._btctl(f"connect {mac}", timeout=12)
            time.sleep(2)
            sinks = self._list_sinks()
            found = False
            for s in sinks:
                if mac.replace(":", "_") in s["name"]:
                    self._set_default_sink(s["name"])
                    self._show_result(f"Conectado! Audio en:\n{s['name'][:20]}")
                    found = True
                    break
            if not found:
                self._show_result(f"Emparejado, pero no se\nencontro sink audio.\nRevisa conexion.")
            self._load_paired()
        elif action == "BACK":
            self._screen = "scan"
            self._draw_result(["ENTER=Escanear de nuevo", "", "BACK=Volver"], "ESCANEO", (100, 200, 255))

    # ── Audio output screen ──

    def _draw_audio_out(self):
        sinks = self._list_sinks()
        current = self._run_cmd(["pactl", "get-default-sink"], timeout=2).strip()
        lines = []
        lines.append(f"=== SALIDA DE AUDIO ===")
        lines.append(f"Actual: {self._get_current_sink_name()}")
        lines.append("")
        if sinks:
            for i, s in enumerate(sinks):
                sel = ">" if i == self._dev_idx else " "
                active = "<<<" if s["name"] == current else "  "
                label = s["name"]
                if "bluez" in label.lower():
                    label = "BT " + label.split(".")[-1][:12]
                elif "fiio" in label.lower():
                    label = "Fiio DAC"
                elif "bcm" in label.lower() or "analog" in label.lower():
                    label = "Jack 3.5mm / HDMI"
                elif "alsa" in label.lower():
                    label = label.split(".")[-1][:14]
                lines.append(f"{sel} {active} {label}")
        else:
            lines.append("(Sin sinks detectados)")
        lines.append("")
        lines.append("ENTER=Cambiar  BACK=Volver  ^v=Navegar")
        self._audio_sinks = sinks
        self._draw_result(lines, "AUDIO", (100, 255, 200), highlight=self._dev_idx if sinks else -1)

    _audio_sinks = []

    def _handle_audio_out(self, action):
        if action == "UP":
            self._dev_idx = max(0, self._dev_idx - 1)
            self._draw_audio_out()
        elif action == "DOWN":
            self._dev_idx = min(len(self._audio_sinks) - 1, self._dev_idx + 1)
            self._draw_audio_out()
        elif action == "ENTER":
            if self._audio_sinks and self._dev_idx < len(self._audio_sinks):
                name = self._audio_sinks[self._dev_idx]["name"]
                self._set_default_sink(name)
                self._screen = "result"
                self._show_result(f"Audio cambiado a:\n{name[:20]}")
        elif action == "BACK":
            self._screen = "main"
            self._draw_main()

    # ── Help screen ──

    def _draw_help(self):
        lines = [
            "=== AYUDA BLUETOOTH ===",
            "",
            "Xbox Controller:",
            "1. Boton Xbox + Pairing",
            "2. Escanea desde el menu",
            "3. Selecciona 'Emparejar'",
            "",
            "Audifonos BT:",
            "1. Modo pairing",
            "2. Escanea y selecciona",
            "3. Usa 'A' para emparejar",
            "   + cambiar audio",
            "",
            "Salida de audio:",
            "Menu > Salida de audio",
            "Selecciona dispositivo",
            "Fiio DAC / Jack / BT",
            "",
            "BACK para volver",
        ]
        self._draw_result(lines, "AYUDA BT", (200, 200, 100))

    # ── Result screen (temporary message) ──

    def _show_result(self, msg):
        lines = msg.splitlines()
        self._draw_result(lines, "RESULTADO", (255, 255, 255))

    # ── Common drawing ──

    def _draw_result(self, lines, title, color, highlight=-1):
        self._fb.blank()
        d = self._fb.draw()
        d.rectangle([(0, 0), (639, 27)], fill=(30, 0, 60))
        d.text((8, 4), title, font=self._fb.font_title, fill=color)
        y = 32
        dev_counter = 0
        for line in lines:
            c = color
            if "Error" in line or "Fallo" in line or "Sin" in line or "DESCONECTADO" in line:
                c = (255, 100, 100)
            elif "CONECTADO" in line or "ACTIVO" in line or "OK" in line or "Conectado" in line:
                c = (100, 255, 100)
            elif ">>" in str(line) or "<<" in str(line):
                c = (100, 255, 100)
            if highlight >= 0 and str(line).startswith(">"):
                c = (255, 255, 0)
            d.text((5, y), str(line)[:62], font=self._fb.font_s, fill=c)
            y += 12
            if y > 230:
                break
        self._fb.update()
