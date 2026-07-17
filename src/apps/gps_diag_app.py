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


_SCREENS = {
    "main": 0,
    "at_test": 1,
    "nmea_raw": 2,
    "antenna": 3,
    "info": 4,
}


class GPSDiagApp:
    def __init__(self, input_mgr, state=None):
        self._input = input_mgr
        self._state = state
        self._fb = FbDisplay(3)
        self._running = False
        self._screen = "main"
        self._menu_idx = 0

        self._diag_data = {
            "modem_ok": None,
            "gps_on": None,
            "has_fix": None,
            "num_sats": 0,
            "last_cgpsinfo": "",
            "last_nmea": "",
            "at_log": [],
        }
        self._running_diag = False
        self._diag_thread = None

    def run(self):
        self._running = True
        self._draw_main()
        while self._running:
            evt = self._input.get_event(timeout=0.1)
            if evt:
                action, _ = evt
                if self._screen == "main":
                    self._handle_main(action)
                elif self._screen in ("at_test", "nmea_raw", "antenna", "info"):
                    if action == "BACK":
                        self._screen = "main"
                        self._draw_main()

        self._fb.blank()
        self._fb.update()

    def _handle_main(self, action):
        items = ["Ejecutar test completo", "AT+CGPSINFO", "NMEA crudo", "Test antena", "Informacion"]
        if action == "UP":
            self._menu_idx = max(0, self._menu_idx - 1)
            self._draw_main()
        elif action == "DOWN":
            self._menu_idx = min(len(items) - 1, self._menu_idx + 1)
            self._draw_main()
        elif action == "ENTER":
            if self._menu_idx == 0:
                self._start_full_test()
            elif self._menu_idx == 1:
                self._screen = "at_test"
                self._run_at_test()
            elif self._menu_idx == 2:
                self._screen = "nmea_raw"
                self._run_nmea_monitor()
            elif self._menu_idx == 3:
                self._screen = "antenna"
                self._run_antenna_test()
            elif self._menu_idx == 4:
                self._screen = "info"
                self._draw_info()
        elif action == "BACK":
            self._running = False

    def _draw_main(self):
        items = ["> Ejecutar test completo", "  AT+CGPSINFO", "  NMEA crudo", "  Test antena", "  Informacion"]
        self._fb.blank()
        d = self._fb.draw()
        d.rectangle([(0, 0), (319, 27)], fill=(0, 60, 20))
        d.text((8, 4), "GPS DIAGNOSTICO", font=self._fb.font_title, fill=(0, 255, 80))
        y = 40
        for i, item in enumerate(items):
            color = (0, 255, 0) if i == self._menu_idx else (120, 120, 120)
            if i == self._menu_idx:
                d.rectangle([(2, y - 2), (317, y + 20)], fill=(0, 40, 10), outline=(0, 255, 0))
            d.text((12, y + 2), item, font=self._fb.font, fill=color)
            y += 28

        ox = 321
        d.rectangle([(ox + 4, 4), (ox + 315, 235)], outline=(0, 255, 80), width=2)
        d.text((ox + 10, 10), "DIAGNOSTICO GPS", font=self._fb.font_title, fill=(0, 255, 80))
        d.text((ox + 10, 45), "Verifica estado del", font=self._fb.font, fill=(180, 180, 180))
        d.text((ox + 10, 67), "modulo SIM7600 GPS", font=self._fb.font, fill=(180, 180, 180))
        d.text((ox + 10, 100), "Pruebas:", font=self._fb.font, fill=(0, 255, 0))
        d.text((ox + 10, 125), "- Comunicacion AT", font=self._fb.font_s, fill=(150, 150, 150))
        d.text((ox + 10, 145), "- Estado del GPS", font=self._fb.font_s, fill=(150, 150, 150))
        d.text((ox + 10, 165), "- Satelites visibles", font=self._fb.font_s, fill=(150, 150, 150))
        d.text((ox + 10, 185), "- Trama NMEA", font=self._fb.font_s, fill=(150, 150, 150))
        d.text((ox + 10, 205), "- Antena", font=self._fb.font_s, fill=(150, 150, 150))
        self._fb.update()

    def _exec_at(self, cmd, port="/dev/ttyUSB2", timeout=3):
        try:
            proc = subprocess.run(
                ["timeout", str(timeout), "bash", "-c", f"echo -e '{cmd}\\r' > {port}; cat {port} & sleep 1; kill %1 2>/dev/null"],
                capture_output=True, text=True, timeout=timeout + 1
            )
            return proc.stdout + proc.stderr
        except Exception as e:
            return f"ERROR: {e}"

    def _detect_ports(self):
        try:
            r = subprocess.run(["ls", "-la", "/dev/ttyUSB*"], capture_output=True, text=True, timeout=2)
            return r.stdout
        except:
            return "No se pudo listar /dev/ttyUSB*"

    def _start_full_test(self):
        self._running_diag = True
        self._draw_result("Ejecutando test completo...\n\n(Esto tomara ~10 segundos)", (0, 255, 255))
        self._diag_thread = threading.Thread(target=self._full_test_worker, daemon=True)
        self._diag_thread.start()

    def _full_test_worker(self):
        lines = []
        lines.append("=== TEST COMPLETO GPS ===")
        lines.append(f"Timestamp: {time.strftime('%H:%M:%S')}")
        lines.append("")

        ports = self._detect_ports()
        lines.append(f"Puertos USB:")
        lines.append(ports if ports else "  Ninguno detectado")
        lines.append("")

        at_resp = self._exec_at("AT", timeout=2)
        if "OK" in at_resp or "AT" in at_resp:
            lines.append("MODEM: OK (responde a AT)")
            self._diag_data["modem_ok"] = True
        else:
            lines.append("MODEM: NO RESPONDE")
            self._diag_data["modem_ok"] = False
            lines.append("")
            lines.append("Verifica:")
            lines.append("1. Cable USB conectado")
            lines.append("2. ls /dev/ttyUSB*")
            lines.append("3. sudo picocom -b 115200 /dev/ttyUSB2")
            self._draw_result("\n".join(lines), (255, 100, 100))
            return

        lines.append("")
        lines.append("--- Test encendido GPS ---")
        lines.append("Enviando AT+CGPS=0 (apagar)...")
        off_resp = self._exec_at("AT+CGPS=0", timeout=3)
        if "OK" in off_resp:
            lines.append("  Apagado: OK")
        else:
            lines.append(f"  Apagado: {off_resp.strip()[:40]}")
        time.sleep(1)

        lines.append("Enviando AT+CGPS=1 (encender)...")
        on_resp = self._exec_at("AT+CGPS=1", timeout=5)
        time.sleep(2)
        if "OK" in on_resp:
            lines.append("  Encendido: OK")
            self._diag_data["gps_on"] = True
        else:
            lines.append(f"  Encendido: {on_resp.strip()[:40]}")
            self._diag_data["gps_on"] = False

        lines.append("")
        cgps_resp = self._exec_at("AT+CGPS?", timeout=2)
        if "+CGPS: 1,1" in cgps_resp:
            lines.append("GPS: ENCENDIDO + FIX")
        elif "+CGPS: 1,0" in cgps_resp:
            lines.append("GPS: ENCENDIDO (sin fix)")
        elif "+CGPS: 0" in cgps_resp:
            lines.append("GPS: APAGADO (no arranco)")
        else:
            lines.append(f"GPS resp: {cgps_resp.strip()[:60]}")

        lines.append("")
        lines.append("Solcitando CGPSINFO...")
        cgpsinfo = self._exec_at("AT+CGPSINFO", timeout=3)
        lines.append(f"  {cgpsinfo.strip()[:80]}")
        if ",," not in cgpsinfo and "CGPSINFO:" in cgpsinfo and len(cgpsinfo) > 30:
            lines.append("  => CON DATOS DE POSICION")
        else:
            lines.append("  => SIN FIX AUN")

        lines.append("")
        lines.append("Estado GPS:")
        status = self._exec_at("AT+CGPSSTATUS?", timeout=2)
        lines.append(f"  {status.strip()[:80]}")

        lines.append("")
        lines.append("Satelites visibles:")
        nmea = self._exec_at("AT+CGPSINFOCFG=1,31", port="/dev/ttyUSB1", timeout=2)
        gsv_check = self._exec_at("", port="/dev/ttyUSB1", timeout=3)
        gsv_count = gsv_check.count("$GPGSV") + gsv_check.count("$GNGSV")
        lines.append(f"  Tramas GSV detectadas: {gsv_count}")
        lines.append("")

        if gsv_count > 0:
            lines.append("ANTENA: OK (recibe satelites)")
        elif self._diag_data["modem_ok"]:
            lines.append("ANTENA: POSIBLE PROBLEMA")
            lines.append("  - Revisa conexion U.FL")
            lines.append("  - Asegura estar al aire libre")
            lines.append("  - Prueba con otra antena")

        lines.append("")
        lines.append("=== TEST COMPLETADO ===")

        def show():
            self._draw_result("\n".join(lines), (255, 255, 100))

        self._fb.blank()
        self._fb.update()
        self._screen = "info"
        self._draw_result("\n".join(lines), (255, 255, 100))

    def _run_at_test(self):
        lines = ["=== PRUEBA DE COMANDOS AT GPS ===", ""]

        lines.append("1. Test basico AT:")
        resp = self._exec_at("AT", timeout=2)
        lines.append(f"   {'OK' if 'OK' in resp else 'NO RESPONDE'}")
        lines.append("")

        lines.append("2. Apagar GPS (AT+CGPS=0):")
        resp = self._exec_at("AT+CGPS=0", timeout=3)
        lines.append(f"   {'OK' if 'OK' in resp else resp.strip()[:40]}")
        time.sleep(1)
        lines.append("")

        lines.append("3. Encender GPS (AT+CGPS=1):")
        resp = self._exec_at("AT+CGPS=1", timeout=5)
        time.sleep(2)
        lines.append(f"   {'OK - GPS encendido' if 'OK' in resp else resp.strip()[:40]}")
        lines.append("")

        lines.append("4. Estado (AT+CGPS?):")
        resp = self._exec_at("AT+CGPS?", timeout=2)
        lines.append(f"   {resp.strip()[:60]}")
        lines.append("")

        lines.append("5. Info posicion (AT+CGPSINFO):")
        resp = self._exec_at("AT+CGPSINFO", timeout=5)
        lines.append(f"   {resp.strip()[:80]}")
        lines.append("")

        lines.append("6. Satelites (AT+CGPSSTATUS?):")
        resp = self._exec_at("AT+CGPSSTATUS?", timeout=3)
        lines.append(f"   {resp.strip()[:60]}")

        lines.append("")
        lines.append("BACK para volver")
        self._draw_result("\n".join(lines), (100, 200, 255))

    def _run_nmea_monitor(self):
        lines = ["=== MONITOR NMEA (ttyUSB1) ===", ""]
        lines.append("Leyendo tramas NMEA...")
        try:
            r = subprocess.run(
                ["timeout", "4", "bash", "-c", "cat /dev/ttyUSB1 2>/dev/null | head -20"],
                capture_output=True, text=True, timeout=5
            )
            raw = r.stdout
            if raw:
                for line in raw.splitlines()[:15]:
                    lines.append(f"  {line[:60]}")
                n_gsv = raw.count("$GPGSV") + raw.count("$GNGSV")
                n_gga = raw.count("$GPGGA") + raw.count("$GNGGA")
                lines.append("")
                lines.append(f"$GPGSV: {n_gsv} tramas")
                lines.append(f"$GPGGA: {n_gga} tramas")
                if n_gsv > 0:
                    lines.append("=> Satelites detectados")
                if n_gga > 0:
                    lines.append("=> Datos de posicion disponibles")
            else:
                lines.append("(Sin datos NMEA)")
                lines.append("Posibles causas:")
                lines.append("- ttyUSB1 no existe")
                lines.append("- GPS no encendido")
                lines.append("- Antena sin señal")
        except Exception as e:
            lines.append(f"Error: {e}")
        lines.append("")
        lines.append("BACK para volver")
        self._draw_result("\n".join(lines), (100, 255, 200))

    def _run_antenna_test(self):
        lines = ["=== TEST DE ANTENA GPS ===", ""]
        lines.append("Paso 1: Satelites visibles via AT")
        status = self._exec_at("AT+CGPSSTATUS?", timeout=3)
        lines.append(f"  {status.strip()[:80]}")
        lines.append("")

        lines.append("Paso 2: Tramas GSV (satelites)")
        try:
            r = subprocess.run(
                ["timeout", "4", "bash", "-c", "cat /dev/ttyUSB1 2>/dev/null | grep -c 'GSV'"],
                capture_output=True, text=True, timeout=5
            )
            gsv_count = int(r.stdout.strip() or 0)
            lines.append(f"  Tramas GSV recibidas: {gsv_count}")
        except:
            gsv_count = 0
            lines.append("  (No se pudo leer ttyUSB1)")

        lines.append("")
        lines.append("Paso 3: Resumen")
        if gsv_count > 3:
            lines.append("ANTENA: PROBABLEMENTE OK")
            lines.append(f"  ({gsv_count} tramas GSV en 4s)")
            lines.append("  El modulo ve satelites,")
            lines.append("  puede tardar en obtener fix")
            lines.append("  si es cold start (5-15 min)")
        elif gsv_count > 0:
            lines.append("ANTENA: SEÑAL DEBIL")
            lines.append("  Pocos satelites detectados")
            lines.append("  Prueba al aire libre")
        else:
            lines.append("ANTENA: POSIBLE FALLA")
            lines.append("  Sin tramas de satelites")
            lines.append("  Verifica:")
            lines.append("  1. Conector U.FL bien puesto")
            lines.append("  2. Antena no danada")
            lines.append("  3. Prueba otra antena GPS")

        lines.append("")
        lines.append("BACK para volver")
        self._draw_result("\n".join(lines), (255, 200, 100))

    def _draw_info(self):
        gps = self._state.get_gps() if self._state else None
        lines = ["=== INFO DEL SISTEMA ===", ""]
        if gps:
            lines.append(f"has_fix: {gps.has_fix}")
            lines.append(f"Lat: {gps.lat:.6f}")
            lines.append(f"Lon: {gps.lon:.6f}")
            lines.append(f"Satelites: {gps.num_satellites}")
            lines.append(f"Altitud: {gps.altitude:.1f}m")
            lines.append(f"Velocidad: {gps.speed_kmh:.1f}km/h")
            lines.append(f"Ultima actualizacion: {time.time() - gps.last_update:.0f}s")
            lines.append("")
            lines.append(f"Cached: {gps.cached_has_fix}")
            lines.append(f"Cached lat: {gps.cached_lat:.6f}")
            lines.append(f"Cached lon: {gps.cached_lon:.6f}")
        else:
            lines.append("(Sin acceso a SystemState)")
        lines.append("")
        lines.append("BACK para volver")
        self._draw_result("\n".join(lines), (200, 200, 255))

    def _draw_result(self, text, color=(255, 255, 255)):
        self._fb.blank()
        d = self._fb.draw()
        d.rectangle([(0, 0), (639, 27)], fill=(0, 40, 20))
        d.text((8, 4), "GPS DIAGNOSTICO", font=self._fb.font_title, fill=color)
        y = 35
        for line in text.splitlines():
            c = color if not line.startswith("  ") else (180, 180, 180)
            if "ERROR" in line or "FALLA" in line or "PROBLEMA" in line:
                c = (255, 100, 100)
            elif "OK" in line or "FIX" in line or "OK)" in line:
                c = (100, 255, 100)
            d.text((6, y), line, font=self._fb.font_s, fill=c)
            y += 13
            if y > 230:
                break
        self._fb.update()
