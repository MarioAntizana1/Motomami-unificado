"""
Módulo para controlar la pantalla OLED GMT020-02 Ver1.1
Utiliza el controlador SSD1306 vía SPI
"""

import time
import board
import busio
import digitalio
from PIL import Image, ImageDraw, ImageFont
from adafruit_ssd1306 import SSD1306_SPI
from config import DISPLAY_CONFIG, DEBUG

class Display:
    def __init__(self):
        """Inicializa la conexión con la pantalla OLED"""
        self.width = DISPLAY_CONFIG['width']
        self.height = DISPLAY_CONFIG['height']
        self.rst_pin = DISPLAY_CONFIG['rst_pin']
        self.dc_pin = DISPLAY_CONFIG['dc_pin']
        self.cs_pin = DISPLAY_CONFIG['cs_pin']
        self.spi_baudrate = DISPLAY_CONFIG['spi_baudrate']
        
        self.display = None
        self.image = None
        self.draw = None
        self.font = None
        
        self._init_display()
    
    def _board_pin(self, pin_number):
        """Convierte un número BCM a un pin board para digitalio."""
        try:
            return getattr(board, f"D{pin_number}")
        except AttributeError:
            raise ValueError(f"Pin GPIO{pin_number} no válido en board")

    def _init_display(self):
        """Inicializa la conexión SPI y la pantalla"""
        try:
            spi = busio.SPI(board.SCLK, MOSI=board.MOSI)
            while not spi.try_lock():
                pass
            try:
                spi.configure(baudrate=self.spi_baudrate, phase=0, polarity=0)
            finally:
                spi.unlock()

            dc = digitalio.DigitalInOut(self._board_pin(self.dc_pin))
            dc.direction = digitalio.Direction.OUTPUT
            reset = digitalio.DigitalInOut(self._board_pin(self.rst_pin))
            reset.direction = digitalio.Direction.OUTPUT
            cs = digitalio.DigitalInOut(self._board_pin(self.cs_pin))
            cs.direction = digitalio.Direction.OUTPUT

            # Reset físico del display
            reset.value = True
            time.sleep(0.1)
            reset.value = False
            time.sleep(0.1)
            reset.value = True
            time.sleep(0.1)

            self.display = SSD1306_SPI(
                self.width,
                self.height,
                spi,
                dc,
                reset,
                cs,
                baudrate=self.spi_baudrate,
            )

            self.display.fill(0)
            self.display.show()

            self.image = Image.new('1', (self.width, self.height))
            self.draw = ImageDraw.Draw(self.image)

            try:
                self.font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
            except Exception:
                self.font = ImageFont.load_default()

            if DEBUG:
                print("[DISPLAY] Pantalla inicializada correctamente")
                print(f"[DISPLAY] Resolución: {self.width}x{self.height}")
        except Exception as e:
            print(f"[ERROR] Error al inicializar la pantalla: {e}")
            raise
    
    def show_text(self, text, x=0, y=0, fill='white'):
        """
        Muestra texto en la pantalla
        
        Args:
            text: Texto a mostrar
            x: Posición X
            y: Posición Y
            fill: Color ('white' o 'black')
        """
        try:
            fill_value = 1 if fill == 'white' else 0
            
            self.draw.text((x, y), text, font=self.font, fill=fill_value)
            self.display.image(self.image)
            self.display.show()
            
            if DEBUG:
                print(f"[DISPLAY] Texto mostrado: '{text}' en posición ({x}, {y})")
        except Exception as e:
            print(f"[ERROR] Error al mostrar texto: {e}")
    
    def clear(self):
        """Limpia la pantalla"""
        try:
            self.image = Image.new('1', (self.width, self.height))
            self.draw = ImageDraw.Draw(self.image)
            self.display.image(self.image)
            self.display.show()
            
            if DEBUG:
                print("[DISPLAY] Pantalla limpiada")
        except Exception as e:
            print(f"[ERROR] Error al limpiar la pantalla: {e}")
    
    def show_image(self, image_path):
        """
        Muestra una imagen en la pantalla
        
        Args:
            image_path: Ruta de la imagen a mostrar
        """
        try:
            img = Image.open(image_path)
            
            # Redimensionar a la resolución de la pantalla
            img = img.resize((self.width, self.height))
            
            # Convertir a modo 1 (blanco y negro)
            img = img.convert('1')
            
            self.display.image(img)
            self.display.show()
            
            if DEBUG:
                print(f"[DISPLAY] Imagen mostrada: {image_path}")
        except Exception as e:
            print(f"[ERROR] Error al mostrar imagen: {e}")
    
    def show_multiline_text(self, text, x=0, y=0, line_spacing=15, fill='white'):
        """
        Muestra texto en múltiples líneas
        
        Args:
            text: Texto a mostrar (puede contener saltos de línea)
            x: Posición X inicial
            y: Posición Y inicial
            line_spacing: Espacio entre líneas
            fill: Color
        """
        try:
            fill_value = 1 if fill == 'white' else 0
            
            lines = text.split('\n')
            current_y = y
            
            for line in lines:
                self.draw.text((x, current_y), line, font=self.font, fill=fill_value)
                current_y += line_spacing
            
            self.display.image(self.image)
            self.display.show()
            
            if DEBUG:
                print(f"[DISPLAY] Texto multilinea mostrado")
        except Exception as e:
            print(f"[ERROR] Error al mostrar texto multilinea: {e}")
    
    def cleanup(self):
        """Limpia los recursos de la pantalla"""
        try:
            if self.display:
                self.display.fill(0)
                self.display.show()
            if DEBUG:
                print("[DISPLAY] Recursos limpios")
        except Exception as e:
            print(f"[ERROR] Error al limpiar recursos: {e}")
