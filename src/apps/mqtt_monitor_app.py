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

        img_left  = self._render_velocimetro(velo)
        img_right = self._render_direccionales(dire)

        full = self._fb.image()
        full.paste(img_left,  (0,   0))
        full.paste(img_right, (320, 0))
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

    # ── Panel derecho: Direccionales / Luces ──

    def _render_direccionales(self, dire) -> Image.Image:
        W, H = 320, 240
        img = Image.new("RGB", (W, H), C_BG)
        d = ImageDraw.Draw(img)

        online = dire is not None and dire.online
        stale = dire is not None and (time.time() - dire.last_update) > 30.0
        has_data = dire is not None and dire.last_update > 0

        # Barra superior
        d.rectangle([(0, 0), (W - 1, 20)], fill=(40, 20, 20))
        d.text((6, 2), "DIRECCIONALES", font=self._f_small, fill=C_WHITE)

        dot_color = C_GREEN if (online and not stale) else (C_YELLOW if stale and has_data else C_RED)
        d.ellipse([(W - 18, 4), (W - 6, 16)], fill=dot_color)
        status_txt = "ONLINE" if (online and not stale) else ("STALE" if stale and has_data else "OFF")
        d.text((W - 85, 2), status_txt, font=self._f_small, fill=dot_color)

        # IP y RSSI
        ip = dire.ip if dire is not None else ""
        rssi = dire.rssi if dire is not None else ""
        if has_data:
            d.text((6, 24), f"IP: {ip}" if ip else "IP: --", font=self._f_small, fill=C_BLUE)
            d.text((6, 38), f"RSSI: {rssi} dBm" if rssi else "RSSI: --", font=self._f_small, fill=C_BLUE)
        else:
            d.text((6, 24), "Esperando datos...", font=self._f_small, fill=C_DIM)

        # ── Estado de las luces ──
        izq  = dire.intermitente_izq if dire is not None else False
        der  = dire.intermitente_der if dire is not None else False
        emer = dire.emergencia if dire is not None else False
        fren = dire.frenado if dire is not None else False
        luz  = dire.luz_nocturna if dire is not None else False
        inten   = dire.intensidad if dire is not None else 0
        inten_n = dire.intensidad_nocturna if dire is not None else 0

        # Ayudantes
        def status_color(on):
            return C_ON if on else C_OFF

        def status_onoff(on):
            return "ON" if on else "OFF"

        y = 58

        # Flecha izquierda
        c_izq = C_YELLOW if izq else C_OFF
        d.polygon([(20, y + 6), (48, y), (48, y + 12)], fill=c_izq)
        d.text((54, y + 2), "IZQUIERDA", font=self._f_small, fill=c_izq)
        d.text((W - 45, y + 2), status_onoff(izq), font=self._f_small, fill=status_color(izq))

        y += 20
        # Flecha derecha
        c_der = C_YELLOW if der else C_OFF
        d.polygon([(W - 20, y + 6), (W - 48, y), (W - 48, y + 12)], fill=c_der)
        d.text((20, y + 2), "DERECHA", font=self._f_small, fill=c_der)
        d.text((W - 45, y + 2), status_onoff(der), font=self._f_small, fill=status_color(der))

        y += 20
        # Emergencia (triángulo de advertencia)
        c_emer = C_RED if emer else C_OFF
        d.polygon([(30, y + 12), (20, y + 2), (40, y + 2)], fill=c_emer)
        d.text((46, y + 2), "EMERGENCIA", font=self._f_small, fill=c_emer)
        d.text((W - 45, y + 2), status_onoff(emer), font=self._f_small, fill=status_color(emer))

        y += 20
        # Frenado
        c_fren = C_RED if fren else C_OFF
        d.rectangle([(22, y + 2), (42, y + 12)], fill=c_fren)
        d.text((48, y + 2), "FRENADO", font=self._f_small, fill=c_fren)
        d.text((W - 45, y + 2), status_onoff(fren), font=self._f_small, fill=status_color(fren))

        y += 20

        # ── Separador ──
        d.line([(10, y), (W - 10, y)], fill=(30, 30, 40))
        y += 4

        # Luz nocturna
        c_noc = C_BLUE if luz else C_OFF
        d.text((16, y), "LUZ NOCTURNA", font=self._f_small, fill=c_noc)
        d.text((W - 45, y), status_onoff(luz), font=self._f_small, fill=status_color(luz))
        y += 14

        # Barra intensidad nocturna
        if has_data:
            bar_x, bar_y = 20, y
            bar_w = W - 110
            pct_n = min(inten_n, 100) / 100.0
            d.rectangle([(bar_x, bar_y), (bar_x + bar_w, bar_y + 6)], fill=(30, 30, 40))
            d.rectangle([(bar_x, bar_y), (bar_x + int(bar_w * pct_n), bar_y + 6)], fill=C_BLUE)
            d.text((bar_x + bar_w + 6, bar_y - 2), f"{inten_n}%", font=self._f_small, fill=C_BLUE)
        y += 10

        # Intensidad general
        d.text((16, y), "INTENSIDAD", font=self._f_small, fill=C_DIM)
        if has_data:
            d.text((W - 45, y), f"{inten}%", font=self._f_small, fill=C_YELLOW)
        y += 14

        # Barra intensidad general
        if has_data:
            bar_x, bar_y = 20, y
            bar_w = W - 110
            pct = min(inten, 100) / 100.0
            d.rectangle([(bar_x, bar_y), (bar_x + bar_w, bar_y + 6)], fill=(30, 30, 40))
            d.rectangle([(bar_x, bar_y), (bar_x + int(bar_w * pct), bar_y + 6)], fill=C_YELLOW)
            d.text((bar_x + bar_w + 6, bar_y - 2), f"{inten}%", font=self._f_small, fill=C_YELLOW)

        # Última actualización
        if has_data:
            from datetime import datetime, timezone, timedelta
            utc = datetime.fromtimestamp(dire.last_update, tz=timezone.utc)
            lt = utc.astimezone(timezone(timedelta(hours=-5)))
            d.text((W - 100, H - 14), lt.strftime("%H:%M:%S"), font=self._f_small, fill=C_DIM)
        else:
            d.text((W - 100, H - 14), "---", font=self._f_small, fill=C_DIM)

        return img

    def _show_splash(self):
        self._fb.blank()
        d = self._fb.draw()
        d.text((60, 100), "MONITOR MQTT", font=_find_font(22), fill=C_BLUE)
        d.text((380, 100), "ESP32 DATOS", font=_find_font(22), fill=C_GREEN)
        d.text((60, 135), "Escuchando motomami/#...", font=_find_font(14), fill=(200, 200, 200))
        self._fb.update()
        time.sleep(1)
