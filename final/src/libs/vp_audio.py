"""vp_audio.py - Deteccion y configuracion del DAC USB Fiio"""
import subprocess
import re


class AudioManager:
    """Detecta el DAC USB Fiio y proporciona opciones de audio."""

    def __init__(self):
        self.device_name = None   # ej: hw:1,0
        self.device_index = None  # PulseAudio index
        self.is_usb_dac = False
        self._detect()

    def _detect(self):
        print("[Audio] Detectando DAC Fiio...")
        try:
            r = subprocess.run(['aplay', '-l'],
                               capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                for line in r.stdout.split('\n'):
                    if any(k in line.lower() for k in ['fiio', 'usb', 'dac']):
                        m = re.search(r'card\s+(\d+)', line)
                        if m:
                            self.device_name = f"hw:{m.group(1)},0"
                            self.is_usb_dac = True
                            print(f"  -> DAC: {line.strip()}")
                            break
        except Exception as e:
            print(f"  Error: {e}")

        if not self.is_usb_dac:
            print("  -> DAC no detectado, usando salida por defecto")
