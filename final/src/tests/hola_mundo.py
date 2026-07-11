# Script básico - Hola Mundo
# Para GMT020-02 2.0 inch SPI Display con Raspberry Pi Zero 2W

import board
import busio
import digitalio
from PIL import Image, ImageDraw, ImageFont
import adafruit_rgb_display.st7789 as st7789
import time

# ====== CONFIGURACIÓN DE PINES ======
cs_pin = digitalio.DigitalInOut(board.CE0)      # Chip Select
dc_pin = digitalio.DigitalInOut(board.D25)      # Data/Command (probé con D27, cambié a D25)
reset_pin = digitalio.DigitalInOut(board.D24)   # Reset (probé con D4, cambié a D24)

# ====== INICIALIZACIÓN SPI ======
# Baudrate reducido a 16MHz para mejor estabilidad
spi = busio.SPI(clock=board.SCK, MOSI=board.MOSI, MISO=board.MISO)

# ====== CREACIÓN DEL DISPLAY ======
# Parámetros estándar para GMT020-02 (320x240)
display = st7789.ST7789(
    spi,
    cs=cs_pin,
    dc=dc_pin,
    rst=reset_pin,
    baudrate=16000000,    # 16MHz
    width=320,            # Resolución correcta para 2.0"
    height=240,           # Resolución correcta para 2.0"
    y_offset=0,           # Intenta 0 primero, luego 20 si no funciona
    x_offset=0,           # Intenta 0 primero, luego 35 si no funciona
    rotation=0,           # 0, 90, 180, 270 según necesites
    bgr=True,             # Modo BGR (estándar para ST7789)
    invert=True           # Invertir colores (generalmente necesario)
)

# ====== BACKLIGHT ======
backlight = digitalio.DigitalInOut(board.D18)
backlight.direction = digitalio.Direction.OUTPUT
backlight.value = True  # Enciende la retroiluminación

# ====== CREAR IMAGEN ======
image = Image.new("RGB", (display.width, display.height), color=(0, 0, 0))
draw = ImageDraw.Draw(image)

# ====== FUENTE (básica, sin fuente personalizada) ======
try:
    # Intenta usar fuente True Type si está disponible
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 40)
except:
    # Si no, usa la fuente por defecto
    font = ImageFont.load_default()

# ====== MOSTRAR HOLA MUNDO ======
print("Inicializando display...")
try:
    # Limpiar pantalla
    draw.rectangle((0, 0, display.width, display.height), fill=(0, 0, 0))
    
    # Escribir texto
    text = "Hola Mundo"
    # Centrar el texto aproximadamente
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    
    x = (display.width - text_width) // 2
    y = (display.height - text_height) // 2
    
    draw.text((x, y), text, font=font, fill=(255, 255, 255))
    
    # Mostrar en la pantalla
    display.image(image)
    print("✓ ¡Hola mundo mostrado en pantalla!")
    
    # Mantener activo por 30 segundos
    time.sleep(30)
    
except Exception as e:
    print(f"✗ Error: {e}")
    print("\nIntenta cambiar estos parámetros si no se ve nada:")
    print("- Cambia 'rotation' a 90, 180 o 270")
    print("- Cambia 'y_offset' a 20")
    print("- Cambia 'x_offset' a 35")
    print("- Cambia 'bgr' a False")
    print("- Cambia 'invert' a False")
    print("- Comprueba que los pines SPI sean: SCK, MOSI, MISO")
    print("- Comprueba que el pin DC sea el correcto (D25 o D27)")

finally:
    backlight.value = False  # Apaga la retroiluminación al salir
    print("Apagada retroiluminación")
