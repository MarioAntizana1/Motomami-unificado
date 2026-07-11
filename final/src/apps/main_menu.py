#!/usr/bin/env python3
"""main_menu.py - FRAMEBUFFER NATIVO edition"""
import os, sys, time, subprocess

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_BASE_DIR = os.path.dirname(_THIS_DIR)
for _p in [os.path.join(_BASE_DIR, 'lib')]:
    if _p not in sys.path: sys.path.insert(0, _p)

import board, digitalio
from fb_display import FramebufferDisplay
from PIL import Image, ImageDraw, ImageFont

try:
    from vp_controller import XboxController
except: XboxController = None

APPS = [
    {"name": "GPS Display",    "cmd": ["sudo", "python3", os.path.join(_THIS_DIR, "gps_display_app.py")],           "color": (100, 255, 100)},
    {"name": "Video Player",   "cmd": ["sudo", "python3", os.path.join(_THIS_DIR, "video_player.py")],              "color": (255, 200,  50)},
    {"name": "Chocolate Doom", "cmd": ["sudo", "python3", os.path.join(_THIS_DIR, "doom_launcher.py")],             "color": (255,  50,  50)},
    {"name": "Music Player",   "cmd": ["sudo", "python3", os.path.join(_THIS_DIR, "music_player.py")],              "color": (200, 100, 255)},
    {"name": "Camara en Vivo", "cmd": ["sudo", "python3", os.path.join(_THIS_DIR, "camera_live.py")],               "color": (255, 100, 100)},
    {"name": "Telemetria",     "cmd": ["sudo", "python3", os.path.join(_BASE_DIR, "lib", "telemetria.py")],          "color": (50,  200, 255)},
    {"name": "SALIR",          "cmd": None,                                                                           "color": (150, 150, 150)},
]

BTNS = {'UP': board.D13, 'DOWN': board.D26, 'ENTER': board.D12, 'BACK': board.D16}

class MainMenu:
    def __init__(self):
        self.idx = 0
        self.running = True
        self.xbox = None
        self.btns = {}
        self.prev = {}

        self.d1 = FramebufferDisplay("/dev/fb1")
        self.d2 = FramebufferDisplay("/dev/fb2")

        try:
            self.ft = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18)
            self.fi = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
            self.fs = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)
            self.fn = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 50)
        except: self.ft = self.fi = self.fs = self.fn = ImageFont.load_default()

        for n, p in BTNS.items():
            try:
                b = digitalio.DigitalInOut(p); b.direction = digitalio.Direction.INPUT; b.pull = digitalio.Pull.DOWN
                self.btns[n] = b; self.prev[n] = False
            except: pass

        self.xbox = XboxController() if XboxController else None
        if self.xbox and self.xbox.connect(): self.xbox.start(); print("[Menu] Xbox OK")

    def draw(self):
        W, H = self.d1.width, self.d1.height  # 320x240
        # Display 1: app list
        i1 = Image.new("RGB", (W, H), (5, 5, 20))
        d1 = ImageDraw.Draw(i1)
        d1.rectangle([(0, 0), (W, 27)], fill=(20, 20, 80))
        d1.text((8, 4), "SISTEMA PRINCIPAL", font=self.ft, fill=(255, 255, 255))
        d1.line([(0, 27), (W, 27)], fill=(60, 60, 120))
        y = 34
        for i, a in enumerate(APPS):
            c = a['color'] if i == self.idx else (130, 130, 150)
            p = "> " if i == self.idx else "  "
            if i == self.idx: d1.rectangle([(3, y-2), (W-3, y+22)], fill=(30,30,70), outline=a['color'])
            d1.text((12, y+2), f"{p}{a['name']}", font=self.fi, fill=c)
            y += 26
        d1.line([(0, H-14), (W, H-14)], fill=(40,40,60))
        d1.text((4, H-12), "^v Nav  A=Lanzar  B=Salir", font=self.fs, fill=(70,70,90))
        self.d1.show(i1)

        # Display 2: selected app panel
        i2 = Image.new("RGB", (W, H), (0, 0, 0))
        d2 = ImageDraw.Draw(i2)
        a = APPS[self.idx]
        d2.rectangle([(4, 4), (W-5, H-5)], outline=a['color'], width=3)
        d2.rectangle([(4, 4), (W-5, 37)], fill=a['color'])
        d2.text((12, 7), a['name'], font=self.ft, fill=(0, 0, 0))
        d2.text((W//2 - 20, 55), str(self.idx + 1), font=self.fn, fill=a['color'])
        d2.text((W//2 - 90, 170), "Presiona A / Enter", font=self.fi, fill=(200,200,200))
        d2.text((W//2 - 77, 193), "para lanzar app", font=self.fs, fill=(100,100,100))
        self.d2.show(i2)

    def launch(self):
        a = APPS[self.idx]
        if a['name'] == "SALIR" or a['cmd'] is None: self.running = False; return
        print(f"[Menu] {a['name']}...")
        # Release GPIO inputs so child app can use them
        self._free_inputs()
        import gc; gc.collect(); time.sleep(0.3)
        # Blank screens
        for d in [self.d1, self.d2]:
            try: d.show(Image.new("RGB", (d.width, d.height), (0, 0, 0)))
            except: pass
        try:
            p = subprocess.Popen(a['cmd']); p.wait()
        except Exception as e: print(f"[Menu] Error: {e}")
        self._init_inputs(); self.draw()

    def _free_inputs(self):
        if self.xbox:
            try: self.xbox.stop()
            except: pass; self.xbox = None
        for b in self.btns.values():
            try: b.deinit()
            except: pass
        self.btns.clear(); self.prev.clear()

    def _init_inputs(self):
        for n, p in BTNS.items():
            try:
                b = digitalio.DigitalInOut(p); b.direction = digitalio.Direction.INPUT; b.pull = digitalio.Pull.DOWN
                self.btns[n] = b; self.prev[n] = False
            except: pass
        self.xbox = XboxController() if XboxController else None
        if self.xbox and self.xbox.connect(): self.xbox.start()

    def read_inputs(self):
        if self.xbox:
            evt = self.xbox.get_event(0.005)
            while evt:
                if evt[0] == 'btn':
                    b = evt[1]
                    if b in (self.xbox.DPAD_U, 300): return 'UP'
                    if b in (self.xbox.DPAD_D, 301): return 'DOWN'
                    if b == self.xbox.A: return 'ENTER'
                    if b == self.xbox.B: return 'BACK'
                evt = self.xbox.get_event(0.005)
        for n, b in self.btns.items():
            try: cur = b.value
            except: cur = False
            if cur and not self.prev.get(n, False): self.prev[n] = True; return n
            self.prev[n] = cur
        return None

    def run(self):
        self.draw(); print("[Menu] Listo.")
        while self.running:
            a = self.read_inputs()
            if a == 'UP': self.idx = max(0, self.idx - 1); self.draw()
            elif a == 'DOWN': self.idx = min(len(APPS)-1, self.idx + 1); self.draw()
            elif a == 'ENTER': self.launch()
            elif a == 'BACK': self.idx = len(APPS)-1; self.launch()
            time.sleep(0.04)
        self._free_inputs()
        for d in [self.d1, self.d2]: d.close()
        print("[Menu] Bye!")

if __name__ == '__main__':
    m = MainMenu()
    try: m.run()
    except KeyboardInterrupt: m._free_inputs(); print("\n[Menu] Interrumpido.")
    except Exception as e: print(f"\n[Menu] Error: {e}"); import traceback; traceback.print_exc()
