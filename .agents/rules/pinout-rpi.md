---
trigger: always_on
---

## Contexto
El sistema tiene **2 pantallas GMT020-02** de 2 pulgadas con controlador ST7789,
compartiendo el mismo bus SPI. Se usan para mostrar mapa y datos de navegaci�n.

## Pines de las Pantallas

| Función | Pantalla #1 (Mapa) | Pantalla #2 (Datos) |
|---------|-------------------|-------------------|
| CS      | GPIO8            | GPIO7            |
| DC      | GPIO27            | GPIO25            |
| RST     | GPIO22            | GPIO23            |
| SCK     | GPIO11 (compartido) | GPIO11 (compartido) |
| MOSI    | GPIO10 (compartido) | GPIO10 (compartido) |

Del cual no debes preocuparte tanto porque ahora esta configurado en el kernel

/home/motomami/final/src/lib/fb_display.py && echo "---" && dmesg | grep -c "graphics fb"
/dev/fb1 /dev/fb2
/dev/fb1: 320x240 16bpp

ambas son de 320x240, en landscape. 
Pantalla1
Pantalla2

Los controles : 
| Botón Arriba | GPIO13 |
| Botón Abajo | GPIO26 |
| Botón Derecha | GPIO5 |
| Botón Izquierda | GPIO6 |
| Botón Enter | GPIO12 |
| Botón Atrás | GPIO16 |
