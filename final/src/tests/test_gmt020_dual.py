#!/usr/bin/env python3
"""
test_gmt020_dual.py

Test para DOS pantallas GMT020-02 (ST7789, 2.0", 240x320)
en Raspberry Pi Zero 2W, compartiendo el mismo bus SPI.

═══════════════════════════════════════════════════════
CONEXIONES:
═══════════════════════════════════════════════════════

Bus SPI0 compartido:
  SCK = GPIO11 (SPI0 SCLK)
  SDA = GPIO10 (SPI0 MOSI)

Pantalla #1 (Display A):
  CS  = GPIO17
  DC  = GPIO27
  RST = GPIO22

Pantalla #2 (Display B):
  CS  = GPIO23
  DC  = GPIO25
  RST = GPIO24

Uso:
  cd src && sudo python3 tests/test_gmt020_dual.py
"""

import time
import sys
import os

# ── Asegurar rutas de módulos locales ──
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_BASE_DIR = os.path.dirname(_THIS_DIR)  # src/
_DRIVERS = os.path.join(_BASE_DIR, 'drivers')
if _DRIVERS not in sys.path:
    sys.path.insert(0, _DRIVERS)

import board
import busio
import digitalio
from PIL import Image, ImageDraw, ImageFont
from st7789_improved import ST7789


# ═══════════════════════════════════════════════════════
#  CONFIGURACIÓN DE PINES — DOS PANTALLAS
# ═══════════════════════════════════════════════════════

# ── Pantalla #1 ──
cs1_pin  = digitalio.DigitalInOut(board.D17)   # GPIO17 — Chip Select (software)
dc1_pin  = digitalio.DigitalInOut(board.D27)   # GPIO27 — Data/Command
rst1_pin = digitalio.DigitalInOut(board.D22)   # GPIO22 — Reset

# ── Pantalla #2 ──
cs2_pin  = digitalio.DigitalInOut(board.D24)   # GPIO24 — Chip Select (software)
dc2_pin  = digitalio.DigitalInOut(board.D25)   # GPIO25 — Data/Command
rst2_pin = digitalio.DigitalInOut(board.D23)   # GPIO23 — Reset


# ═══════════════════════════════════════════════════════
#  INICIALIZACIÓN SPI + DISPLAYS
# ═══════════════════════════════════════════════════════
print("╔══════════════════════════════════════════╗")
print("║  Test DUAL GMT020-02 — 2 pantallas       ║")
print("╚══════════════════════════════════════════╝")
print()

# ── Inicializar bus SPI (compartido) ──
print("[1/6] Inicializando SPI bus (compartido)...")
spi = busio.SPI(clock=board.SCK, MOSI=board.MOSI)
print("      SCK = GPIO11, MOSI = GPIO10")
print()

# ── Crear Display #1 ──
print("[2/6] Creando Display #1...")
print("      CS  = GPIO17")
print("      DC  = GPIO27")
print("      RST = GPIO22")

display1 = ST7789(
    spi,
    cs1_pin,
    dc1_pin,
    rst1_pin,
    width=240,
    height=320,
    rotation=0,
    baudrate=24000000,
    display_name='2.0"',
    bgr=False,
    invert=True,
)
print(f"      → Display #1 listo: {display1.width}x{display1.height}")
print()

# ── Crear Display #2 ──
print("[3/6] Creando Display #2...")
print("      CS  = GPIO23")
print("      DC  = GPIO25")
print("      RST = GPIO24")

display2 = ST7789(
    spi,
    cs2_pin,
    dc2_pin,
    rst2_pin,
    width=240,
    height=320,
    rotation=0,
    baudrate=24000000,
    display_name='2.0"',
    bgr=False,
    invert=True,
)
print(f"      → Display #2 listo: {display2.width}x{display2.height}")
print()


# ═══════════════════════════════════════════════════════
#  FUNCIONES DE TEST
# ═══════════════════════════════════════════════════════

def test_colores(display, label):
    """Rellena toda la pantalla con colores primarios."""
    colores = [
        ("ROJO",    (255, 0,   0)),
        ("VERDE",   (0,   255, 0)),
        ("AZUL",    (0,   0,   255)),
        ("BLANCO",  (255, 255, 255)),
        ("NEGRO",   (0,   0,   0)),
    ]

    print(f"      [{label}] Test de colores sólidos...")
    for nombre, color in colores:
        print(f"         → {nombre} {color}")
        display.fill(color)
        time.sleep(1)


def test_rectangulos(display, label):
    """Dibuja rectángulos de distintos colores."""
    print(f"      [{label}] Test de rectángulos...")
    display.fill((0, 0, 0))  # Limpiar

    w = display.width // 2
    h = display.height // 2

    display.fill_rect(0, 0, w, h, (255, 0, 0))       # Arriba-izq: rojo
    display.fill_rect(w, 0, w, h, (0, 255, 0))        # Arriba-der: verde
    display.fill_rect(0, h, w, h, (0, 0, 255))        # Abajo-izq: azul
    display.fill_rect(w, h, w, h, (255, 255, 0))      # Abajo-der: amarillo

    print(f"         → 4 cuadrantes: Rojo | Verde | Azul | Amarillo")


def test_texto(display, label, titulo_texto, sub_texto, color_titulo=(0, 255, 128)):
    """Muestra texto centrado usando PIL Image + ImageDraw."""
    print(f"      [{label}] Test de texto...")

    image = Image.new("RGB", (display.width, display.height), (0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Fuentes
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

    # Título
    bbox = draw.textbbox((0, 0), titulo_texto, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = (display.width - tw) // 2
    y = (display.height // 2) - th - 10
    draw.text((x, y), titulo_texto, font=font, fill=color_titulo)

    # Subtítulo
    bbox2 = draw.textbbox((0, 0), sub_texto, font=font_small)
    sw = bbox2[2] - bbox2[0]
    sx = (display.width - sw) // 2
    sy = y + th + 20
    draw.text((sx, sy), sub_texto, font=font_small, fill=(100, 180, 255))

    # Etiqueta del display (ej: "#1" o "#2")
    info = label
    bbox3 = draw.textbbox((0, 0), info, font=font_small)
    iw = bbox3[2] - bbox3[0]
    ix = (display.width - iw) // 2
    iy = sy + 25
    draw.text((ix, iy), info, font=font_small, fill=(255, 200, 50))

    # Borde decorativo
    draw.rectangle(
        [5, 5, display.width - 6, display.height - 6],
        outline=color_titulo,
        width=2,
    )

    display.display(image)


# ═══════════════════════════════════════════════════════
#  EJECUCIÓN
# ═══════════════════════════════════════════════════════
if __name__ == "__main__":
    displays = [
        (display1, "Display #1 (GPIO17)"),
        (display2, "Display #2 (GPIO23)"),
    ]

    try:
        # ── Test 1: Colores en ambas pantallas (una a la vez) ──
        print("[4/6] Test de colores — ambas pantallas")
        for disp, label in displays:
            test_colores(disp, label)
        print(f"      ✓ Test de colores completado")
        print()

        # ── Test 2: Rectángulos en ambas ──
        print("[5/6] Test de rectángulos — ambas pantallas")
        for disp, label in displays:
            test_rectangulos(disp, label)
        print(f"      ✓ Test de rectángulos completado")
        print()

        # ── Test 3: Texto diferente en cada pantalla ──
        print("[6/6] Test de texto — cada pantalla con mensaje propio")
        test_texto(
            display1, "Display #1 (GPIO17)",
            "Hola Mundo!",
            "GMT020-02 + RPi Zero 2W",
            color_titulo=(0, 255, 128),  # verde
        )
        test_texto(
            display2, "Display #2 (GPIO23)",
            "Dual Screen!",
            "SPI0 - CS via GPIO23",
            color_titulo=(255, 128, 0),  # naranja
        )
        print(f"      ✓ Test de texto completado")
        print()

        # ── Resumen final ──
        print("══════════════════════════════════════════")
        print("  ✓ TODOS LOS TESTS PASARON")
        print("  Display #1 (GPIO17): 'Hola Mundo!'  (verde)")
        print("  Display #2 (GPIO23): 'Dual Screen!'  (naranja)")
        print("══════════════════════════════════════════")
        print()
        print("Pantallas activas por 30 segundos...")
        print("(Ctrl+C o botón físico Atrás para salir antes)")
        
        btn_back = None
        try:
            btn_back = digitalio.DigitalInOut(board.D16)
            btn_back.direction = digitalio.Direction.INPUT
            btn_back.pull = digitalio.Pull.DOWN
        except Exception:
            pass  # GPIO busy (menú principal) o no disponible

        start_t = time.time()
        while time.time() - start_t < 30:
            if btn_back and btn_back.value:
                print("\n→ Saliendo por botón físico...")
                break
            time.sleep(0.1)

    except KeyboardInterrupt:
        print("\n→ Interrumpido por el usuario")
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        print()
        print("═══ DIAGNÓSTICO ═══")
        print("1. ¿SPI habilitado?  → sudo raspi-config → Interface → SPI")
        print("2. ¿Pines correctos?")
        print("   Display #1: CS=GPIO17, DC=GPIO27, RST=GPIO22")
        print("   Display #2: CS=GPIO23, DC=GPIO25, RST=GPIO24")
        print("3. ¿Ejecutas con sudo? → sudo python3 test_gmt020_dual.py")
        print("4. ¿Cables bien conectados?")
        print("   - MOSI(GPIO10) y SCK(GPIO11) en PARALELO a ambas pantallas")
        print("   - CS de cada pantalla a su GPIO correspondiente")
        sys.exit(1)
    finally:
        # Apagar ambas pantallas al salir
        for disp, label in displays:
            try:
                disp.fill((0, 0, 0))
                disp.display_off()
                print(f"→ {label} apagada")
            except Exception:
                pass
