# Configuración de pines GPIO y parámetros de la aplicación

# Configuración de la pantalla GMT020-02
DISPLAY_CONFIG = {
    'width': 128,           # Ancho en píxeles
    'height': 64,           # Alto en píxeles
    'rst_pin': 4,           # GPIO4 para Reset
    'dc_pin': 27,           # GPIO27 para Data/Command
    'cs_pin': 22,           # GPIO22 para Chip Select
    'spi_baudrate': 8000000,# Baudrate SPI recomendado
}

# Configuración de la cámara
CAMERA_CONFIG = {
    'resolution': (640, 480),  # Resolución de captura
    'framerate': 90,              # Fotogramas por segundo
    'rotation': 0,                # Rotación en grados
}

# Modo de depuración
DEBUG = True
