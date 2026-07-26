"""
mqtt_monitor_app.py - Monitor de mensajes MQTT de los ESP32.
Pantalla 1 (izq/fb2): velocímetro (velocidad, distancia, pulsos)
Pantalla 2 (der/fb1): direccionales (luces, señales, intensidades)
Usa ambas pantallas en canvas 640x240.
"""
import os
import sys
import time
import math

_SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in [_SRC, os.path.join(_SRC, 'libs'), os.path.join(_SRC, 'core')]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from PIL import Image, ImageDraw
from libs.fb_display import FbDisplay, _find_font

# Colores (misma paleta que gps_display_app)
C_GREEN  = (0, 220, 80)
C_BLUE   = (0, 180, 255)
C_YELLOW = (255, 200, 50)
C_RED    = (255, 60, 60)
C_DIM    = (80, 80, 80)
C_BG     = (0, 0, 0)
C_WHITE  = (220, 220, 220)
C_OFF    = (40, 40, 40)
C_ON     = (0, 220, 80)

MONITOR_REFRESH = 0.3  # segundos entre renders


class MqttMonitorApp:
    """
    App monitor MQTT. Se ejecuta hasta que el usuario presiona BACK.
    """

    def __init__(self, input_mgr, state=None):
        self._input = input_mgr
        self._state = state
        self._fb = FbDisplay(3)
        self._running = False

        self._f_huge   = _find_font(56)
        self._f_big    = _find_font(32)
        self._f_normal = _find_font(14)
        self._f_small  = _find_font(11)

    def run(self):
        self._running = True
        self._show_splash()
        last_render = 0

        while self._running:
            evt = self._input.get_event(timeout=0.02)
            if evt:
                action, _ = evt
                if action == "BACK":
                    self._running = False

            now = time.time()
            if now - last_render >= MONITOR_REFRESH:
                self._render()
                last_render = now

        self._fb.blank()
        self._fb.update()

    def _render(self):
        velo = self._state.get_esp32_velocimetro() if self._state else None
        dire = self._state.get_esp32_direccionales() if self._state else None
        inp  = self._state.get_esp32_input() if self._state else None

        img_left   = self._render_velocimetro(velo)
        img_dire   = self._render_direccionales(dire, 160)
        img_input  = self._render_input(inp, 80)

        full = self._fb.image()
        full.paste(img_left,   (0,   0))
        full.paste(img_dire,   (320, 0))
        full.paste(img_input,  (320, 160))
        self._fb.update()

    # ── Panel izquierdo: Velocímetro ──

    def _render_velocimetro(self, velo) -> Image.Image:
        W, H = 320, 240
        img = Image.new("RGB", (W, H), C_BG)
        d = ImageDraw.Draw(img)

        online = velo is not None and velo.online
        stale = velo is not None and (time.time() - velo.last_update) > 5.0
        has_data = velo is not None and velo.last_update > 0

        # Barra superior
        d.rectangle([(0, 0), (W - 1, 20)], fill=(20, 20, 40))
        d.text((6, 2), "VELOCIMETRO", font=self._f_small, fill=C_WHITE)

        dot_color = C_GREEN if (online and not stale) else (C_YELLOW if stale and has_data else C_RED)
        d.ellipse([(W - 18, 4), (W - 6, 16)], fill=dot_color)
        status_txt = "ONLINE" if (online and not stale) else ("STALE" if stale and has_data else "OFF")
        d.text((W - 85, 2), status_txt, font=self._f_small, fill=dot_color)

        # ── Velocidad (grande) ──
        speed = velo.speed if velo is not None else 0
        speed_str = f"{speed:.1f}"
        d.text((20, 36), speed_str, font=self._f_huge, fill=C_WHITE if has_data else C_DIM)
        bb = d.textbbox((0, 0), speed_str, font=self._f_huge)
        d.text((24 + bb[2], 80), "km/h", font=self._f_normal, fill=C_DIM)

        # Barra de velocidad gráfica
        bar_w = W - 40
        bar_x = 20
        bar_y = 110
        fill_pct = min(speed / 120.0, 1.0) if has_data else 0
        d.rectangle([(bar_x, bar_y), (bar_x + bar_w, bar_y + 8)], fill=(30, 30, 40))
        d.rectangle([(bar_x, bar_y), (bar_x + int(bar_w * fill_pct), bar_y + 8)],
                    fill=C_GREEN if fill_pct < 0.7 else (C_YELLOW if fill_pct < 0.9 else C_RED))

        # ── Línea separadora ──
        d.line([(10, 128), (W - 10, 128)], fill=(30, 30, 40))

        # ── Distancia, Odómetro, Pulsos ──
        dist = velo.distance if velo is not None else 0
        odo  = velo.odometro if velo is not None else 0
        pul  = velo.pulses if velo is not None else 0

        y = 136
        d.text((14, y),     "DISTANCIA", font=self._f_small, fill=C_DIM)
        d.text((14, y + 14), f"{dist:.3f} km", font=self._f_normal, fill=C_BLUE if has_data else C_DIM)

        d.text((W // 2 + 10, y),     "ODOMETRO", font=self._f_small, fill=C_DIM)
        d.text((W // 2 + 10, y + 14), f"{odo:.3f} km", font=self._f_normal, fill=C_YELLOW if has_data else C_DIM)

        y = 176
        d.text((14, y),     "PULSOS", font=self._f_small, fill=C_DIM)
        d.text((14, y + 14), f"{pul:,}" if has_data else "--", font=self._f_normal, fill=C_WHITE if has_data else C_DIM)

        # ── Última actualización ──
        if has_data:
            from datetime import datetime, timezone, timedelta
            utc = datetime.fromtimestamp(velo.last_update, tz=timezone.utc)
            lt = utc.astimezone(timezone(timedelta(hours=-5)))
            d.text((W - 100, H - 14), lt.strftime("%H:%M:%S"), font=self._f_small, fill=C_DIM)
        else:
            d.text((W - 100, H - 14), "---", font=self._f_small, fill=C_DIM)

        return img

    # ── Panel derecho: Direccionales (compactado) ──

    def _render_direccionales(self, dire, H=160) -> Image.Image:
        W = 320
        img = Image.new("RGB", (W, H), C_BG)
        d = ImageDraw.Draw(img)

        online = dire is not None and dire.online
        stale = dire is not None and (time.time() - dire.last_update) > 30.0
        has_data = dire is not None and dire.last_update > 0

        # Barra superior
        d.rectangle([(0, 0), (W - 1, 18)], fill=(40, 20, 20))
        d.text((6, 1), "DIRECCIONALES", font=self._f_small, fill=C_WHITE)

        dot_color = C_GREEN if (online and not stale) else (C_YELLOW if stale and has_data else C_RED)
        d.ellipse([(W - 16, 3), (W - 6, 13)], fill=dot_color)
        status_txt = "ONLINE" if (online and not stale) else ("STALE" if stale and has_data else "OFF")
        d.text((W - 78, 1), status_txt, font=self._f_small, fill=dot_color)

        # IP / RSSI / ID en una línea
        ip = dire.ip if dire is not None else ""
        rssi = dire.rssi if dire is not None else ""
        did = dire.id if dire is not None else ""
        if has_data:
            parts = []
            if ip: parts.append(f"IP:{ip}")
            if rssi: parts.append(f"RSSI:{rssi}dBm")
            if did: parts.append(f"ID:{did}")
            line = "  ".join(parts) if parts else "Esperando datos..."
            d.text((6, 20), line, font=self._f_small, fill=C_BLUE)
        else:
            d.text((6, 20), "Esperando datos...", font=self._f_small, fill=C_DIM)

        # ── Estado de las luces ──
        izq  = dire.intermitente_izq if dire is not None else False
        der  = dire.intermitente_der if dire is not None else False
        emer = dire.emergencia if dire is not None else False
        fren = dire.frenado if dire is not None else False
        luz  = dire.luz_nocturna if dire is not None else False
        inten   = dire.intensidad if dire is not None else 0
        inten_n = dire.intensidad_nocturna if dire is not None else 0

        def status_color(on):
            return C_ON if on else C_OFF

        def status_onoff(on):
            return "ON" if on else "OFF"

        y = 38

        # Fila 1: Izquierda
        c_izq = C_YELLOW if izq else C_OFF
        d.polygon([(14, y + 5), (36, y), (36, y + 10)], fill=c_izq)
        d.text((40, y), "IZQUIERDA", font=self._f_small, fill=c_izq)
        d.text((W - 40, y), status_onoff(izq), font=self._f_small, fill=status_color(izq))

        y += 14
        # Fila 2: Derecha
        c_der = C_YELLOW if der else C_OFF
        d.polygon([(W - 14, y + 5), (W - 36, y), (W - 36, y + 10)], fill=c_der)
        d.text((14, y), "DERECHA", font=self._f_small, fill=c_der)
        d.text((W - 40, y), status_onoff(der), font=self._f_small, fill=status_color(der))

        y += 14
        # Fila 3: Emergencia
        c_emer = C_RED if emer else C_OFF
        d.polygon([(24, y + 10), (15, y + 1), (33, y + 1)], fill=c_emer)
        d.text((38, y), "EMERGENCIA", font=self._f_small, fill=c_emer)
        d.text((W - 40, y), status_onoff(emer), font=self._f_small, fill=status_color(emer))

        y += 14
        # Fila 4: Frenado
        c_fren = C_RED if fren else C_OFF
        d.rectangle([(16, y + 1), (34, y + 9)], fill=c_fren)
        d.text((38, y), "FRENADO", font=self._f_small, fill=c_fren)
        d.text((W - 40, y), status_onoff(fren), font=self._f_small, fill=status_color(fren))

        y += 14
        # Separador + nocturna
        d.line([(10, y), (W - 10, y)], fill=(30, 30, 40))
        y += 2

        c_noc = C_BLUE if luz else C_OFF
        d.text((14, y), f"NOCTURNA:{status_onoff(luz)}", font=self._f_small, fill=c_noc)
        if has_data:
            d.text((140, y), f"INT:{inten}%  NOC:{inten_n}%", font=self._f_small, fill=C_YELLOW)

        y += 12
        # Barras de intensidad
        if has_data:
            bar_w = W - 30
            pct_n = min(inten_n, 100) / 100.0
            d.rectangle([(15, y), (15 + int(bar_w * pct_n), y + 3)], fill=C_BLUE)
            pct = min(inten, 100) / 100.0
            d.rectangle([(15, y + 4), (15 + int(bar_w * pct), y + 7)], fill=C_YELLOW)

        # Timestamp
        if has_data:
            from datetime import datetime, timezone, timedelta
            utc = datetime.fromtimestamp(dire.last_update, tz=timezone.utc)
            lt = utc.astimezone(timezone(timedelta(hours=-5)))
            d.text((W - 80, H - 12), lt.strftime("%H:%M:%S"), font=self._f_small, fill=C_DIM)

        return img

    # ── Panel inferior derecho: Input ──

    def _render_input(self, inp, H=80) -> Image.Image:
        W = 320
        img = Image.new("RGB", (W, H), C_BG)
        d = ImageDraw.Draw(img)

        online = inp is not None and inp.online
        stale = inp is not None and (time.time() - inp.last_update) > 30.0
        has_data = inp is not None and inp.last_update > 0

        d.rectangle([(0, 0), (W - 1, 18)], fill=(20, 40, 20))
        d.text((6, 1), "INPUT", font=self._f_small, fill=C_WHITE)

        dot_color = C_GREEN if (online and not stale) else (C_YELLOW if stale and has_data else C_RED)
        d.ellipse([(W - 16, 3), (W - 6, 13)], fill=dot_color)
        status_txt = "ONLINE" if (online and not stale) else ("STALE" if stale and has_data else "OFF")
        d.text((W - 78, 1), status_txt, font=self._f_small, fill=dot_color)

        ip = inp.ip if inp is not None else ""
        rssi = inp.rssi if inp is not None else ""
        iid = inp.id if inp is not None else ""
        if has_data:
            parts = []
            if ip: parts.append(f"IP:{ip}")
            if rssi: parts.append(f"RSSI:{rssi}dBm")
            if iid: parts.append(f"ID:{iid}")
            line = "  ".join(parts) if parts else "Conectado"
            d.text((6, 22), line, font=self._f_small, fill=C_BLUE)
        else:
            d.text((6, 22), "Esperando datos...", font=self._f_small, fill=C_DIM)

        if has_data:
            from datetime import datetime, timezone, timedelta
            utc = datetime.fromtimestamp(inp.last_update, tz=timezone.utc)
            lt = utc.astimezone(timezone(timedelta(hours=-5)))
            d.text((W - 80, H - 12), lt.strftime("%H:%M:%S"), font=self._f_small, fill=C_DIM)

        return img

    def _show_splash(self):
        self._fb.blank()
        d = self._fb.draw()
        d.text((60, 100), "MONITOR MQTT", font=_find_font(22), fill=C_BLUE)
        d.text((380, 100), "ESP32 DATOS", font=_find_font(22), fill=C_GREEN)
        d.text((60, 135), "Escuchando motomami/#...", font=_find_font(14), fill=(200, 200, 200))
        self._fb.update()
        time.sleep(1)
