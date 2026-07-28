Archivos y funciones.

- /Motomami-direccionales-esp32c6
Aca los compontentes que lleva son :
1 XIAO SEEED ESP32C6
1 Matriz de NEO-PiXELS

Su funcion:
Son las luces traseras de la moto

- /Motomami-input-esp32c6

Los componentes son 
1 XIAO SEEED ESP32C6
Botones y switches para intermitentes, frenos y luz nocturna.

Su funcion:
Sustituye los mandos de la moto.

- /Motomami-velocimetro-temperatura-esp32c6

1 XIAO SEEED ESP32C6
1 Switch magnetico tipo cranshaft position de los automoviles (si es reciclado) de 3 pines
En el futuro proximo pondre un sensor DS18B20 que va ir al motor y un sensor de temperatura y humedad i2c para que sea ambiental

Funciones:
Lee los pasos de la rueda, son 3 imanes posicionados en el aro de una rueda de moto (parte delantera)
Da Kilometraje recorrido
Velocidad 
Guarda la informacion de los pasos y de los kilometros recorridos 

-----------------------------------------

Funciones generales
Todos los modulos deben enviar por MQTT los siguientes parametros para control:

Estado: si esta conectado o no
RSSI: para ver la potencia de la señal
IP: para ver que IP esta agarrando de la red
ID: contador de mensajes

Todos deben tener el OTA Activado
HTTP Server en el ESP	El ESP corre un servidor HTTP con endpoint /ota que acepta POST del binario

Todos deben tener una reconexion instantanea del Wifi y del servidor MQTT
Esto porque la raspberry pi tarda en arrancar y a veces por diversas razones la conexion puede fallar
Entonces, para esto debes acumular la información en memoria, y cuando se envia se libera. --- EXCEPTO: el del velocimetro que debe acumular el kilometraje y los pulsos
Para esto, cada mensaje debe tener un id, es un contador de mensajes.
Entonces la RPI puede saber si le falta un mensaje o no.

