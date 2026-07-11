#!/usr/bin/env python3
"""test_gmt020.py

Test completo para pantalla GMT020-02 (ST7789, 2.0", 240x320)
en Raspberry Pi Zero 2W.

Pines:
  CS  = CE0   (GPIO8)
  DC  = D27   (GPIO27)
  RST = D4    (GPIO4)
  SCK = GPIO11 (SPI0 SCLK)
  SDA = GPIO10 (SPI0 MOSI)

Uso:
  sudo python3 test_gmt020.py
"""

import time
import sys
import board
import busio
import digitalio
from PIL import Image, ImageDraw, ImageFont
from st7789_improved import ST7789


# ═══════════════════════════════════════════════════════
#  CONFIGURACIÓN DE PINES
# ═══════════════════════════════════════════════════════
cs_pin    = digitalio.DigitalInOut(board.CE0)   # Chip Select — CE0 (GPIO8)
dc_pin    = digitalio.DigitalInOut(board.D27)   # Data/Command — GPIO27
rst_pin   = digitalio.DigitalInOut(board.D4)    # Reset — GPIO4


# ═══════════════════════════════════════════════════════
#  INICIALIZACIÓN SPI + DISPLAY
# ═══════════════════════════════════════════════════════
print("╔══════════════════════════════════════════╗")
print("║  Test GMT020-02 — st7789_improved.py     ║")
print("╚══════════════════════════════════════════╝")
print()

print("[1/5] Inicializando SPI bus...")
spi = busio.SPI(clock=board.SCK, MOSI=board.MOSI)

print("[2/5] Creando driver ST7789...")
print("      CS  = CE0  (GPIO8)")
print("      DC  = D27  (GPIO27)")
print("      RST = D4   (GPIO4)")
print("      Resolución: 240×320  (display_name='2.0\"')")
print("      Baudrate: 24 MHz")
print("      invert=True, bgr=False")

display = ST7789(
    spi,
    cs_pin,
    dc_pin,
    rst_pin,
    width=240,
    height=320,
    rotation=0,
    baudrate=24000000,
    display_name='2.0"',
    bgr=False,
    invert=True,
)

print(f"      → Display listo: {display.width}x{display.height}")
print()


# ═══════════════════════════════════════════════════════
#  TEST 1: Colores sólidos (fill_rect)
# ═══════════════════════════════════════════════════════
def test_colores():
    """Rellena toda la pantalla con colores primarios."""
    colores = [
        ("ROJO",    (255, 0,   0)),
        ("VERDE",   (0,   255, 0)),
        ("AZUL",    (0,   0,   255)),
        ("BLANCO",  (255, 255, 255)),
        ("NEGRO",   (0,   0,   0)),
    ]

    print("[3/5] Test de colores sólidos (fill)...")
    for nombre, color in colores:
        print(f"      → {nombre} {color}")
        display.fill(color)
        time.sleep(1)

    print("      ✓ Test de colores completado")
    print()


# ═══════════════════════════════════════════════════════
#  TEST 2: Rectángulos
# ═══════════════════════════════════════════════════════
def test_rectangulos():
    """Dibuja rectángulos de distintos colores."""
    print("[4/5] Test de rectángulos (fill_rect)...")
    display.fill((0, 0, 0))  # Limpiar

    # Cuatro cuadrantes de colores
    w = display.width // 2
    h = display.height // 2

    display.fill_rect(0, 0, w, h, (255, 0, 0))       # Arriba-izq: rojo
    display.fill_rect(w, 0, w, h, (0, 255, 0))        # Arriba-der: verde
    display.fill_rect(0, h, w, h, (0, 0, 255))        # Abajo-izq: azul
    display.fill_rect(w, h, w, h, (255, 255, 0))      # Abajo-der: amarillo

    print("      → 4 cuadrantes: Rojo | Verde | Azul | Amarillo")
    time.sleep(3)
    print("      ✓ Test de rectángulos completado")
    print()


# ═══════════════════════════════════════════════════════
#  TEST 3: Texto "Hola Mundo" con PIL
# ═══════════════════════════════════════════════════════
def test_texto():
    """Muestra texto centrado usando PIL Image + ImageDraw."""
    print("[5/5] Test de texto (PIL → display)...")

    # Crear imagen negra del tamaño del display
    image = Image.new("RGB", (display.width, display.height), (0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Intentar cargar fuente TrueType, si no, usar la default
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 32
        )
        font_small = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16
        )
    except OSError:
        font = ImageFont.load_default()
        font_small = font

    # Título centrado
    titulo = "Hola Mundo!"
    bbox = draw.textbbox((0, 0), titulo, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = (display.width - tw) // 2
    y = (display.height // 2) - th - 10
    draw.text((x, y), titulo, font=font, fill=(0, 255, 128))

    # Subtítulo
    sub = "GMT020-02 + RPi Zero 2W"
    bbox2 = draw.textbbox((0, 0), sub, font=font_small)
    sw = bbox2[2] - bbox2[0]
    sx = (display.width - sw) // 2
    sy = y + th + 20
    draw.text((sx, sy), sub, font=font_small, fill=(100, 180, 255))

    # Info de driver
    info = "st7789_improved.py"
    bbox3 = draw.textbbox((0, 0), info, font=font_small)
    iw = bbox3[2] - bbox3[0]
    ix = (display.width - iw) // 2
    iy = sy + 25
    draw.text((ix, iy), info, font=font_small, fill=(255, 200, 50))

    # Borde decorativo
    draw.rectangle(
        [5, 5, display.width - 6, display.height - 6],
        outline=(0, 200, 100),
        width=2,
    )

    # Enviar imagen al display
    display.display(image)
    print("      → 'Hola Mundo!' mostrado en pantalla")
    print("      ✓ Test de texto completado")
    print()


# ═══════════════════════════════════════════════════════
#  EJECUCIÓN
# ═══════════════════════════════════════════════════════
if __name__ == "__main__":
    try:
        test_colores()
        test_rectangulos()
        test_texto()

        print("══════════════════════════════════════════")
        print("  ✓ TODOS LOS TESTS PASARON")
        print("    La pantalla debería mostrar:")
        print("    'Hola Mundo!' en verde sobre negro")
        print("    con borde verde y subtítulos")
        print("══════════════════════════════════════════")
        print()
        print("Pantalla activa por 30 segundos...")
        print("(Ctrl+C para salir antes)")
        time.sleep(30)

    except KeyboardInterrupt:
        print("\n→ Interrumpido por el usuario")
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        print()
        print("═══ DIAGNÓSTICO ═══")
        print("1. ¿SPI habilitado?  → sudo raspi-config → Interface → SPI")
        print("2. ¿Pines correctos? → CS=CE0, DC=GPIO27, RST=GPIO4")
        print("3. ¿Ejecutas con sudo? → sudo python3 test_gmt020.py")
        print("4. ¿Cables bien conectados? → Revisa MOSI(GPIO10), SCK(GPIO11)")
        sys.exit(1)
    finally:
        # Apagar pantalla al salir
        try:
            display.fill((0, 0, 0))
            display.display_off()
            print("→ Pantalla apagada")
        except Exception:
            pass
