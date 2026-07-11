# Script básico - Hola Mundo
# Para GMT020-02 2.0 inch SPI Display con Raspberry Pi Zero 2W

import board
import busio
import digitalio
from PIL import Image, ImageDraw, ImageFont
from st7789_custom import ST7789
import time

# ====== CONFIGURACIÓN DE PINES ======
cs_pin = digitalio.DigitalInOut(board.CE0)      # Chip Select
dc_pin = digitalio.DigitalInOut(board.D25)      # Data/Command (probé con D27, cambié a D25)
reset_pin = digitalio.DigitalInOut(board.D4)   # Reset (probé con D4, cambié a D24)
backlight_pin = digitalio.DigitalInOut(board.D18)  # Retroiluminación, si tu pantalla la usa

# ====== INICIALIZACIÓN SPI ======
# Baudrate configurado a 24MHz para el ST7789
spi = busio.SPI(clock=board.SCK, MOSI=board.MOSI, MISO=board.MISO)

# ====== CREACIÓN DEL DISPLAY ======
# Ajuste basado en el código ESP32: la pantalla se inicializa como 240x320
display = ST7789(
    spi,
    cs_pin,
    dc_pin,
    reset_pin,
    baudrate=24000000,    # 24MHz
    width=240,
    height=320,
    rotation=3,           # Igual que setRotation(3) en el ESP32
    x_offset=0,
    y_offset=0,
    bgr=False,
    invert=True,
    backlight=backlight_pin,
)

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
    text = "hola mundo"
    # Centrar el texto aproximadamente
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    
    x = (display.width - text_width) // 2
    y = (display.height - text_height) // 2
    
    draw.text((x, y), text, font=font, fill=(255, 255, 255))
    
    # Mostrar en la pantalla
    display.display(image)
    print("✓ ¡hola mundo mostrado en pantalla!")
    
    # Mantener activo por 30 segundos
    time.sleep(30)
    
except Exception as e:
    print(f"✗ Error: {e}")
    print("\nComprueba los pines SPI y el pin de datos (DC), especialmente en Raspberry Pi")
