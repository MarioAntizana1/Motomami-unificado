#!/usr/bin/env python3
"""
android_auto_app.py - Interfaz de Android Auto para MotoMami
En esta versión optimizada, esta app lanzará openauto u otro
software de Android Auto.
"""
import os
import sys
import time
import subprocess

_SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from libs.fb_display import FbDisplay, _find_font
from PIL import Image, ImageDraw

class AndroidAutoApp:
    def __init__(self, input_mgr, state=None):
        self._input = input_mgr
        self._state = state
        self._fb = FbDisplay(3)
        self._running = False
        self._proc = None

    def run(self):
        self._running = True
        self._render_message("Iniciando Android Auto...")
        
        # Aquí se lanzaría el proceso real de Android Auto (ej: openauto)
        # Para propósitos de este sistema unificado, simularemos la interfaz o 
        # proporcionaremos las instrucciones si no está instalado.
        
        self._render_message("Android Auto no instalado o configurado.\n\nPresiona ATRAS para salir.")
        
        while self._running:
            evt = self._input.get_event(timeout=0.1)
            if evt:
                action, _ = evt
                if action == "BACK":
                    self._running = False
                    
        self._fb.blank()
        self._fb.update()

    def _render_message(self, text):
        self._fb.blank()
        img = self._fb.image()
        draw = ImageDraw.Draw(img)
        font = _find_font(20)
        draw.text((20, 50), text, font=font, fill=(0, 255, 0))
        self._fb.update()
