"""st7789_improved.py

Improved ST7789 driver for Raspberry Pi combining simplicity and Adafruit flexibility.

Key improvements over st7789_custom.py:
  - Auto-calculate column/row offsets based on display size
  - Dynamic width/height adjustment during rotation
  - Support for multiple display models (240x240, 135x240, 240x320)
  - Additional control methods: display_on(), display_off(), invert(), sleep()
  - Better documentation and structure
  - Compatible with Adafruit API patterns (simplified)

Based on analysis of:
  - Adafruit_ST7789 (C++ Arduino library)
  - st7789_custom.py (our initial Python implementation)
"""

import time
import struct
import busio
import digitalio
from PIL import Image

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

# Timing delays
_T_DELAY = 0.00001  # 10 µs for SPI protocol delays
_SPI_CHUNK_SIZE = 4096 #2048  # Max bytes per SPI transfer (kernel spidev limit)

# ST7789 Command Set
_SWRESET = 0x01
_SLPIN = 0x10
_SLPOUT = 0x11
_PTLON = 0x12
_NORON = 0x13
_INVOFF = 0x20
_INVON = 0x21
_DISPOFF = 0x28
_DISPON = 0x29
_CASET = 0x2A
_RASET = 0x2B
_RAMWR = 0x2C
_PTLAR = 0x30
_MADCTL = 0x36
_COLMOD = 0x3A

# MADCTL Bits
_MX = 0x40   # Column address order
_MY = 0x80   # Row address order
_MV = 0x20   # Row/column exchange
_ML = 0x10   # Vertical refresh order
_RGB = 0x00  # RGB pixel order
_BGR = 0x08  # BGR pixel order


def _color565(red: int, green: int, blue: int) -> int:
    """Convert RGB888 to RGB565 (16-bit)."""
    return ((red & 0xF8) << 8) | ((green & 0xFC) << 3) | (blue >> 3)


class ST7789:
    """ST7789 2.0\" SPI display driver for Raspberry Pi Zero 2W.
    
    This driver is optimized for:
      - GMT020-02 (240x320, 2.0\")
      - ST7789 1.3\" (240x240)
      - ST7789 1.14\" (135x240)
    
    The internal ST7789 controller has a 320x240 pixel RAM, but different
    physical displays use different portions (windows). Offsets are
    automatically calculated.
    
    Args:
        spi (busio.SPI): SPI bus instance
        cs (digitalio.DigitalInOut): Chip Select pin
        dc (digitalio.DigitalInOut): Data/Command pin
        rst (digitalio.DigitalInOut): Reset pin
        width (int): Display width in pixels (default 240)
        height (int): Display height in pixels (default 320)
        rotation (int): Initial rotation 0-3 (default 0)
        baudrate (int): SPI clock speed (default 24 MHz)
        display_name (str): Display model name for auto-offset calculation
                          '2.0\"' (default), '1.3\"', '1.14\"', 'custom'
        bgr (bool): Use BGR color order instead of RGB (default False)
        invert (bool): Invert display colors (default True for some displays)
        backlight (digitalio.DigitalInOut): Optional backlight control pin
    """
    
    # Display model configurations
    DISPLAY_MODELS = {
        '2.0\"': {'width': 240, 'height': 320},
        '1.9\"': {'width': 240, 'height': 320},
        '1.69\"': {'width': 240, 'height': 280},
        '1.47\"': {'width': 172, 'height': 320},
        '1.3\"': {'width': 240, 'height': 240},
        '1.14\"': {'width': 135, 'height': 240},
    }
    
    def __init__(
        self,
        spi: busio.SPI,
        cs: digitalio.DigitalInOut,
        dc: digitalio.DigitalInOut,
        rst: digitalio.DigitalInOut,
        width: int = 240,
        height: int = 320,
        rotation: int = 0,
        baudrate: int = 40000000,
        display_name: str = '2.0\"',
        bgr: bool = False,
        invert: bool = True,
        backlight: digitalio.DigitalInOut = None,
    ):
        self.spi = spi
        self.cs = cs
        self.dc = dc
        self.rst = rst
        self._width = width
        self._height = height
        self._rotation = rotation & 3
        self.baudrate = baudrate
        self.bgr = bgr
        self._invert = invert
        self.backlight = backlight
        
        # Calculate offsets based on display model
        self._calculate_offsets(width, height, display_name)
        
        # Initialize hardware
        self._configure_pins()
        self._configure_spi()
        self._configure_backlight()
        self._reset()
        self._initialize_display()

    def _calculate_offsets(self, width: int, height: int, display_name: str):
        """Calculate column and row offsets based on display size.
        
        ST7789 has internal 320x240 RAM. Different displays use different
        portions of this RAM (windows).
        """
        if display_name == '1.3\"' and width == 240 and height == 240:
            # 1.3\" display (240x240 from 320x240 RAM)
            # Right-justified: X offset = 0, Y offset = 80
            self._colstart = 0
            self._colstart2 = 0
            self._rowstart = 80  # (320 - 240) = 80
            self._rowstart2 = 0
        elif display_name == '1.14\"' and width == 135 and height == 240:
            # 1.14\" display (135x240, centered, odd)
            self._rowstart = self._rowstart2 = (320 - height) // 2  # 40
            self._colstart = (240 - width + 1) // 2  # 53
            self._colstart2 = (240 - width) // 2     # 52
        else:
            # Default: 240x320 and other sizes
            # For GMT020-02 (240x320, or 320x240 in landscape):
            # When width > height (landscape), we're in swapped mode
            if width > height:
                # Landscape: use 0 offsets since the driver handles swapping
                self._rowstart = self._rowstart2 = 0
                self._colstart = self._colstart2 = 0
            else:
                # Portrait: standard offsets
                self._rowstart = self._rowstart2 = (320 - height) // 2
                self._colstart = self._colstart2 = (240 - width) // 2
        
        # Internal position trackers for rotated displays
        self._xstart = self._colstart
        self._ystart = self._rowstart
    
    def _configure_pins(self):
        """Configure CS, DC, RST pins as outputs."""
        for pin in (self.cs, self.dc, self.rst):
            pin.direction = digitalio.Direction.OUTPUT
        self.cs.value = True
        self.dc.value = True
    
    def _configure_spi(self):
        """Configure SPI clock and mode."""
        while not self.spi.try_lock():
            pass
        try:
            self.spi.configure(baudrate=self.baudrate, phase=0, polarity=0)
        finally:
            self.spi.unlock()
    
    def _configure_backlight(self):
        """Configure backlight pin if provided."""
        if self.backlight is not None:
            self.backlight.direction = digitalio.Direction.OUTPUT
            self.backlight.value = True
    
    def _reset(self):
        """Perform hardware reset sequence."""
        self.rst.value = True
        time.sleep(0.05)
        self.rst.value = False
        time.sleep(0.05)
        self.rst.value = True
        time.sleep(0.15)
    
    def _write(self, data: bytes):
        """Write raw bytes to SPI with timing delay."""
        while not self.spi.try_lock():
            pass
        try:
            self.spi.write(data)
        finally:
            self.spi.unlock()
        time.sleep(_T_DELAY)
    
    def _command(self, cmd: int, data: bytes = None):
        """Send a command with optional data bytes."""
        self.dc.value = False
        self.cs.value = False
        self._write(bytes([cmd]))
        self.cs.value = True
        time.sleep(_T_DELAY)
        if data is not None:
            self._data(data)
    
    def _data(self, data: bytes):
        """Send data bytes in chunks to avoid SPI buffer overflow."""
        if not isinstance(data, (bytes, bytearray)):
            data = bytes(data)
        self.dc.value = True
        self.cs.value = False
        # Send in chunks to avoid kernel spidev buffer limits
        for i in range(0, len(data), _SPI_CHUNK_SIZE):
            self._write(data[i:i + _SPI_CHUNK_SIZE])
        self.cs.value = True
        time.sleep(_T_DELAY)
    
    def _initialize_display(self):
        """Initialize ST7789 with Adafruit-style generic sequence."""
        # Software reset
        self._command(_SWRESET)
        time.sleep(0.15)
        
        # Sleep out
        self._command(_SLPOUT)
        time.sleep(0.12)
        
        # Color mode: 0x55 = 16-bit RGB565
        self._command(_COLMOD, bytes([0x55]))
        time.sleep(0.01)
        
        # Memory access control (will be set by rotation)
        self._command(_MADCTL, bytes([0x08]))
        
        # Inversion control
        if self._invert:
            self._command(_INVON)
        else:
            self._command(_INVOFF)
        time.sleep(0.01)
        
        # Normal display mode
        self._command(_NORON)
        time.sleep(0.01)
        
        # Display on
        self._command(_DISPON)
        time.sleep(0.12)
        
        # Apply initial rotation
        self.set_rotation(self._rotation)
    
    def set_rotation(self, rotation: int):
        """Set display rotation (0-3) and update internal dimensions.
        
        Like Adafruit implementation:
          - Adjusts MADCTL register
          - Updates _xstart and _ystart
          - Swaps width/height if needed
        """
        self._rotation = rotation & 3
        
        # Rotation lookup table: (MADCTL, update_width_height)
        if self._rotation == 0:
            # 0°: portrait, normal
            madctl = _MX | _MY | _RGB
            self._xstart = self._colstart
            self._ystart = self._rowstart
            self.width = self._width
            self.height = self._height
        elif self._rotation == 1:
            # 90°: landscape, right
            madctl = _MY | _MV | _RGB
            self._xstart = self._rowstart
            self._ystart = self._colstart2
            self.width = self._height
            self.height = self._width
        elif self._rotation == 2:
            # 180°: portrait, inverted
            madctl = _RGB
            self._xstart = self._colstart2
            self._ystart = self._rowstart2
            self.width = self._width
            self.height = self._height
        else:  # self._rotation == 3
            # 270°: landscape, left
            madctl = _MX | _MV | _RGB
            self._xstart = self._rowstart2
            self._ystart = self._colstart
            self.width = self._height
            self.height = self._width
        
        if self.bgr:
            madctl |= _BGR
        
        self._command(_MADCTL, bytes([madctl]))
    
    def set_addr_window(self, x: int, y: int, w: int, h: int):
        """Set the drawing window using (x, y, width, height) coordinates.
        
        Applies offsets internally. Similar to Adafruit API.
        All coordinates are sent as 16-bit values (required for >255 pixel displays).
        """
        x += self._xstart
        y += self._ystart
        
        # Safety: clamp to valid range for 'H' format (0-65535)
        if x < 0 or y < 0 or x + w - 1 < 0 or y + h - 1 < 0:
            print(f"[DEBUG set_addr_window] NEGATIVE! x={x}, y={y}, w={w}, h={h}, "
                  f"_xstart={self._xstart}, _ystart={self._ystart}, "
                  f"_colstart={self._colstart}, _colstart2={self._colstart2}, "
                  f"_rowstart={self._rowstart}, _rowstart2={self._rowstart2}, "
                  f"rotation={self._rotation}")
        x = max(0, x)
        y = max(0, y)
        x1 = max(0, x + w - 1)
        y1 = max(0, y + h - 1)
        
        # CASET (Column Address Set) — 16-bit start and end column
        self._command(_CASET, struct.pack('>HH', x, x1))
        
        # RASET (Row Address Set) — 16-bit start and end row
        self._command(_RASET, struct.pack('>HH', y, y1))
        
        # RAMWR (RAM Write) - prepare to send pixel data
        self._command(_RAMWR)
    
    def display_on(self):
        """Turn display on."""
        self._command(_DISPON)
        time.sleep(0.01)
    
    def display_off(self):
        """Turn display off."""
        self._command(_DISPOFF)
        time.sleep(0.01)
    
    def invert(self, enable: bool):
        """Enable or disable color inversion."""
        if enable:
            self._command(_INVON)
        else:
            self._command(_INVOFF)
        time.sleep(0.01)
        self._invert = enable
    
    def sleep(self, enable: bool):
        """Enable or disable sleep mode."""
        if enable:
            self._command(_SLPIN)
        else:
            self._command(_SLPOUT)
        time.sleep(0.12)
    
    def write_pixel(self, x: int, y: int, color=(255, 255, 255)):
        """Write a single pixel at (x, y)."""
        if not (0 <= x < self.width and 0 <= y < self.height):
            raise ValueError(f'Pixel ({x}, {y}) out of bounds ({self.width}x{self.height})')
        
        self.set_addr_window(x, y, 1, 1)
        pixel = _color565(*color)
        self._data(bytes([(pixel >> 8) & 0xFF, pixel & 0xFF]))
    
    def fill_rect(self, x: int, y: int, w: int, h: int, color=(0, 0, 0)):
        """Fill a rectangle with the given color."""
        if w <= 0 or h <= 0:
            return
        
        # Clip to display bounds
        if x + w > self.width:
            w = self.width - x
        if y + h > self.height:
            h = self.height - y
        
        self.set_addr_window(x, y, w, h)
        
        # Generate pixel buffer efficiently using struct.pack + repetition
        pixel = _color565(*color)
        pixel_bytes = struct.pack('>H', pixel)
        buf = pixel_bytes * (w * h)
        
        self._data(buf)
    
    def fill(self, color=(0, 0, 0)):
        """Fill entire display with color."""
        self.fill_rect(0, 0, self.width, self.height, color)
    
    def display_raw(self, rgb565_data: bytes):
        """Display raw RGB565 bytes directly (no PIL conversion).
        
        Used by fb_daemon.py for zero-overhead frame pushing.
        Data must be self.width * self.height * 2 bytes in RGB565 big-endian format.
        """
        if self.width <= 0 or self.height <= 0:
            print(f"[DEBUG display_raw] INVALID dimensions! width={self.width}, height={self.height}")
            return
        expected = self.width * self.height * 2
        if len(rgb565_data) != expected:
            print(f"[DEBUG display_raw] Size mismatch: {len(rgb565_data)} != {expected}")
            return
        self.set_addr_window(0, 0, self.width, self.height)
        self._data(rgb565_data)

    def display(self, image):
        """Display a PIL Image on the screen.
        
        Image is resized to match display dimensions if needed.
        Uses numpy for fast RGB888→RGB565 conversion when available.
        """
        if image.size != (self.width, self.height):
            image = image.resize((self.width, self.height))
        
        rgb = image.convert('RGB')
        
        if _HAS_NUMPY:
            # Fast path: numpy vectorized conversion (~100x faster)
            arr = np.array(rgb, dtype=np.uint16)
            r = arr[:, :, 0]
            g = arr[:, :, 1]
            b = arr[:, :, 2]
            rgb565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            # Convert to big-endian bytes
            buf = rgb565.astype('>u2').tobytes()
        else:
            # Slow path: pure Python fallback
            pixel_count = self.width * self.height
            buf = bytearray(pixel_count * 2)
            idx = 0
            for r, g, b in rgb.getdata():
                pixel = _color565(r, g, b)
                buf[idx] = (pixel >> 8) & 0xFF
                buf[idx + 1] = pixel & 0xFF
                idx += 2
        
        if self.width <= 0 or self.height <= 0:
            print(f"[DEBUG display] INVALID dimensions! width={self.width}, height={self.height}, "
                  f"rotation={self._rotation}, _width={self._width}, _height={self._height}")
            return
        
        self.set_addr_window(0, 0, self.width, self.height)
        self._data(buf)

