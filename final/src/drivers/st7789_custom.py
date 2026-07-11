"""Controlador ST7789 mínimo para Raspberry Pi usando busio/digitalio.

Basado en la secuencia de inicialización del driver Arduino Adafruit_ST7789.
"""

import time
import struct

import busio
import digitalio
from PIL import Image

# Small timing delays (seconds). PDF specs give ns; use small microsecond delays here.
_T_DELAY = 0.00001  # 10 µs
_SPI_CHUNK_SIZE = 4096  # Max bytes per SPI transfer

# ST7789 Comandos
_SWRESET = 0x01
_SLPOUT = 0x11
_COLMOD = 0x3A
_MADCTL = 0x36
_INVON = 0x21
_INVOFF = 0x20
_NORON = 0x13
_DISPON = 0x29
_CASET = 0x2A
_RASET = 0x2B
_RAMWR = 0x2C

_MX = 0x40
_MY = 0x80
_MV = 0x20
_BGR = 0x08
_RGB = 0x00


def _color565(red, green, blue):
    return ((red & 0xF8) << 8) | ((green & 0xFC) << 3) | (blue >> 3)


class ST7789:
    def __init__(
        self,
        spi: busio.SPI,
        cs: digitalio.DigitalInOut,
        dc: digitalio.DigitalInOut,
        rst: digitalio.DigitalInOut,
        width: int = 240,
        height: int = 320,
        rotation: int = 0,
        baudrate: int = 24000000,
        x_offset: int = 0,
        y_offset: int = 0,
        bgr: bool = False,
        invert: bool = True,
        backlight: digitalio.DigitalInOut = None,
    ):
        self.spi = spi
        self.cs = cs
        self.dc = dc
        self.rst = rst
        self.width = width
        self.height = height
        self.rotation = rotation & 3
        self.baudrate = baudrate
        self.x_offset = x_offset
        self.y_offset = y_offset
        self.bgr = bgr
        self.invert = invert
        self.backlight = backlight

        self._configure_pins()
        self._configure_spi()
        self._configure_backlight()
        self._reset()
        self._initialize_display()

    def _configure_pins(self):
        for pin in (self.cs, self.dc, self.rst):
            pin.direction = digitalio.Direction.OUTPUT
        self.cs.value = True
        self.dc.value = True

    def _configure_spi(self):
        while not self.spi.try_lock():
            pass
        try:
            self.spi.configure(baudrate=self.baudrate, phase=0, polarity=0)
        finally:
            self.spi.unlock()

    def _configure_backlight(self):
        if self.backlight is not None:
            self.backlight.direction = digitalio.Direction.OUTPUT
            self.backlight.value = True

    def _reset(self):
        self.rst.value = True
        time.sleep(0.05)
        self.rst.value = False
        time.sleep(0.05)
        self.rst.value = True
        time.sleep(0.15)

    def _write(self, data):
        while not self.spi.try_lock():
            pass
        try:
            self.spi.write(data)
        finally:
            self.spi.unlock()
        # brief delay to meet timing requirements
        time.sleep(_T_DELAY)

    def _command(self, command, data: bytes = None):
        """Send a ST7789 command and optional data bytes."""
        self.dc.value = False
        self.cs.value = False
        self._write(bytes([command]))
        self.cs.value = True
        time.sleep(_T_DELAY)
        if data is not None:
            self.write_data(data)

    def write_cmd(self, command, data: bytes = None):
        """Public alias for sending a command."""
        self._command(command, data)

    def write_data(self, data):
        """Send data bytes to the display RAM/parameters."""
        if not isinstance(data, (bytes, bytearray)):
            data = bytes(data)
        self.dc.value = True
        self.cs.value = False
        # Send in chunks to avoid kernel spidev buffer limits
        for i in range(0, len(data), _SPI_CHUNK_SIZE):
            self._write(data[i:i + _SPI_CHUNK_SIZE])
        self.cs.value = True
        time.sleep(_T_DELAY)

    def _data(self, data):
        self.write_data(data)

    def _initialize_display(self):
        # Use the generic ST7789 initialization table from the Arduino driver
        self._command(_SWRESET)
        time.sleep(0.15)
        self._command(_SLPOUT)
        time.sleep(0.12)
        self._command(_COLMOD, bytes([0x55]))
        time.sleep(0.01)
        # default MADCTL value as in Arduino generic init; rotation will be set below
        self._command(_MADCTL, bytes([0x08]))
        if self.invert:
            self._command(_INVON)
            time.sleep(0.01)
        self._command(_NORON)
        time.sleep(0.01)
        self._command(_DISPON)
        time.sleep(0.12)
        self.set_rotation(self.rotation)

    def set_rotation(self, rotation: int):
        rotation = rotation & 3
        self.rotation = rotation

        if rotation == 0:
            madctl = _MX | _MY | _RGB
        elif rotation == 1:
            madctl = _MY | _MV | _RGB
        elif rotation == 2:
            madctl = _RGB
        else:
            madctl = _MX | _MV | _RGB

        if self.bgr:
            madctl |= _BGR

        self._command(_MADCTL, bytes([madctl]))

    def _set_window(self, x0: int, y0: int, x1: int, y1: int):
        x0 += self.x_offset
        x1 += self.x_offset
        y0 += self.y_offset
        y1 += self.y_offset

        # Send as 16-bit values (required for coordinates > 255)
        self._command(_CASET, struct.pack('>HH', x0, x1))
        self._command(_RASET, struct.pack('>HH', y0, y1))
        self._command(_RAMWR)

    def display(self, image):
        if image.size != (self.width, self.height):
            image = image.resize((self.width, self.height))

        rgb = image.convert('RGB')
        pixel_count = self.width * self.height
        buffer = bytearray(pixel_count * 2)
        idx = 0

        for r, g, b in rgb.getdata():
            pixel = _color565(r, g, b)
            buffer[idx] = (pixel >> 8) & 0xFF
            buffer[idx + 1] = pixel & 0xFF
            idx += 2

        self._set_window(0, 0, self.width - 1, self.height - 1)
        self._data(buffer)

    def write_pixel(self, x: int, y: int, color=(255, 255, 255)):
        """Write a single pixel at (x, y) using direct ST7789 commands."""
        if not (0 <= x < self.width and 0 <= y < self.height):
            raise ValueError('Pixel out of bounds')
        self._set_window(x, y, x, y)
        pixel = _color565(*color)
        self._data(bytes([(pixel >> 8) & 0xFF, pixel & 0xFF]))

    def fill(self, color=(0, 0, 0)):
        image = Image.new('RGB', (self.width, self.height), color=color)
        self.display(image)
