#!/usr/bin/env python3
"""
sim7600_gps.py - Control del GPS del SIM7600-G vía comandos AT

El SIM7600-G tiene el GPS integrado en el módulo, no es un receptor
GPS externo. Hay que activarlo con comandos AT por el puerto serie.

Flujo:
  1. Detectar SIM7600 por USB (vendor=1e0e, product=9001)
  2. Encontrar el puerto AT (/dev/ttyUSB2 generalmente)
  3. Enviar AT+CGPS=1 para activar GPS
  4. Configurar AT+CGPSINFOCFG=1,31
  5. Leer AT+CGPSINFO periódicamente

Puertos típicos del SIM7600-G:
  /dev/ttyUSB0 - DIAG (para actualizaciones)
  /dev/ttyUSB1 - NMEA (datos GPS crudos, tramas $GPGGA etc.)
  /dev/ttyUSB2 - AT (comandos de control)
  /dev/ttyUSB3 - PPP (datos)
"""

import time
import threading
import re
import copy
import serial
import serial.tools.list_ports
from typing import Optional, Callable
from dataclasses import dataclass


@dataclass
class SIM7600GPSData:
    """Datos parseados del GPS del SIM7600-G"""
    # De AT+CGPSINFO
    latitude: float = 0.0
    lat_direction: str = "N"
    longitude: float = 0.0
    lon_direction: str = "W"
    date: str = ""          # DDMMYY
    time: str = ""          # HHMMSS.SS
    altitude: float = 0.0   # Metros
    speed_kmh: float = 0.0
    track_angle: float = 0.0

    # Estado
    gps_on: bool = False
    has_fix: bool = False
    num_satellites: int = 0

    # Timestamp de recepción
    received_at: float = 0.0

    def get_coordinates_decimal(self) -> tuple:
        """Retorna (lat, lon) en grados decimales"""
        lat_dd = self._nmea_to_decimal(self.latitude, self.lat_direction)
        lon_dd = self._nmea_to_decimal(self.longitude, self.lon_direction)
        return (lat_dd, lon_dd)

    @staticmethod
    def _nmea_to_decimal(nmea_coord: float, direction: str) -> float:
        """Convierte DDMM.MMMM a DD.DDDDD"""
        if nmea_coord == 0:
            return 0.0
        degrees = int(nmea_coord / 100)
        minutes = nmea_coord - (degrees * 100)
        decimal = degrees + (minutes / 60.0)
        if direction in ('S', 'W'):
            decimal = -decimal
        return decimal

    def __str__(self) -> str:
        lat, lon = self.get_coordinates_decimal()
        return (f"SIM7600 GPS: {'FIX' if self.has_fix else 'NO FIX'} | "
                f"Lat={lat:.6f} Lon={lon:.6f} | "
                f"Alt={self.altitude:.1f}m | Vel={self.speed_kmh:.1f}km/h | "
                f"Sats={self.num_satellites}")


class SIM7600GPS:
    """
    Controlador del GPS integrado en el SIM7600-G.

    Se comunica por comandos AT para activar/leer el GPS.

    Args:
        at_port: Puerto AT (ej: /dev/ttyUSB2)
        baudrate: Velocidad del puerto serie
        auto_start: Si True, activa el GPS automáticamente al iniciar
    """

    # Patrones de respuesta
    # Formato AT+CGPSINFO:
    #   +CGPSINFO: <lat>,<ns>,<lon>,<ew>,<date>,<time>,<alt>,<speed>,<course>
    #   date=DDMMYY (6 digitos, SIN punto), time=HHMMSS.SS, speed=knots, course=degrees
    RE_CGPSINFO = re.compile(
        r'\+CGPSINFO:\s*'
        r'([\d.]*),([NS]),'       # lat, dir
        r'([\d.]*),([EW]),'       # lon, dir
        r'(\d{6}),'               # fecha DDMMYY (sin decimal)
        r'(\d{6}\.\d*),'          # hora HHMMSS.SS
        r'([\d.]*),'              # altitud (metros)
        r'([\d.]*),'              # speed (knots)
        r'([\d.]*)'               # track angle (grados)
    )

    RE_CGPSSTATUS = re.compile(
        r'\+CGPSSTATUS:\s*(\S+)'
    )

    def __init__(
        self,
        at_port: str = "/dev/ttyUSB2",
        nmea_port: str = "/dev/ttyUSB1",
        baudrate: int = 115200,
    ):
        self.at_port = at_port
        self.nmea_port = nmea_port
        self.baudrate = baudrate

        self.serial = None
        self.nmea_serial = None
        self.running = False
        self.thread = None
        self.lock = threading.Lock()

        self.data = SIM7600GPSData()
        self._callback: Optional[Callable] = None
        self._at_buffer = b""

        # Para reconexión
        self.consecutive_errors = 0
        self.max_errors = 5
        self._last_satellite_request = 0.0

    def set_callback(self, callback: Callable):
        """Callback llamado con cada actualización de datos GPS"""
        self._callback = callback

    def start(self):
        """Activa el GPS e inicia el hilo de lectura"""
        if self.running:
            return

        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        print(f"[SIM7600-GPS] Iniciando en {self.at_port} @ {self.baudrate} baud")

    def stop(self):
        """Apaga el GPS y cierra el puerto"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=3)

        try:
            if self.serial and self.serial.is_open:
                self._send_at("AT+CGPS=0")  # Apagar GPS
                self.serial.close()
        except:
            pass
        try:
            if self.nmea_serial and self.nmea_serial.is_open:
                self.nmea_serial.close()
        except:
            pass
        print("[SIM7600-GPS] Detenido")

    def get_data(self) -> SIM7600GPSData:
        """Obtiene los últimos datos GPS (thread-safe)"""
        with self.lock:
            return copy.copy(self.data)

    def _run(self):
        """Bucle principal: conecta, activa GPS, lee datos"""
        while self.running:
            try:
                # Conectar al puerto AT
                if not self._connect():
                    time.sleep(2)
                    continue

                # Activar GPS
                if not self._init_gps():
                    print("[SIM7600-GPS] Error activando GPS, reintentando...")
                    time.sleep(3)
                    continue

                # Bucle de lectura
                self._read_loop()

            except serial.SerialException as e:
                print(f"[SIM7600-GPS] Error serial: {e}")
                self.consecutive_errors += 1
            except Exception as e:
                print(f"[SIM7600-GPS] Error: {e}")
                self.consecutive_errors += 1

            # Si hay muchos errores consecutivos, esperar más
            if self.consecutive_errors >= self.max_errors:
                print("[SIM7600-GPS] Demasiados errores, esperando 30s...")
                time.sleep(30)
                self.consecutive_errors = 0
            else:
                time.sleep(2)

    def _connect(self) -> bool:
        """Abre el puerto serie al SIM7600"""
        try:
            if self.serial and self.serial.is_open:
                return True

            print(f"[SIM7600-GPS] Abriendo {self.at_port}...")
            self.serial = serial.Serial(
                port=self.at_port,
                baudrate=self.baudrate,
                timeout=1,
                write_timeout=1,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                xonxoff=False,
                rtscts=False,
            )
            # Pequeña espera para estabilizar
            time.sleep(0.5)
            # Vaciar buffers
            self.serial.reset_input_buffer()
            self.serial.reset_output_buffer()

            # Verificar que el módulo responde
            if self._send_at("AT"):
                print(f"[SIM7600-GPS] Puerto {self.at_port} abierto y respondiendo")
                self.consecutive_errors = 0
                return True
            else:
                print(f"[SIM7600-GPS] {self.at_port} no responde a AT")
                self.serial.close()
                return False

        except serial.SerialException as e:
            print(f"[SIM7600-GPS] No se pudo abrir {self.at_port}: {e}")
            if self.serial:
                try:
                    self.serial.close()
                except:
                    pass
            self.serial = None
            return False

    def _init_gps(self) -> bool:
        """Activa y configura el GPS del SIM7600"""
        if not self.serial or not self.serial.is_open:
            return False

        print("[SIM7600-GPS] Configurando GPS...")

        # Forzar apagado del GPS para poder configurar el formato (CGPSINFOCFG requiere GPS desactivado)
        self._send_at("AT+CGPS=0")
        time.sleep(1.0)

        # Configurar formato: NMEA extendido (31 = lat+lon+alt+speed+track+date+time+sats)
        resp = self._send_at("AT+CGPSINFOCFG=1,31")
        if resp is None:
            print("[SIM7600-GPS] Advertencia: No se pudo configurar formato (CGPSINFOCFG)")
        else:
            print("[SIM7600-GPS] Formato NMEA configurado: modo=1, formato=31")

        # Activar GPS
        resp = self._send_at("AT+CGPS=1")
        if resp is None:
            print("[SIM7600-GPS] Error: No se pudo activar el GPS (AT+CGPS=1)")
            return False

        time.sleep(2.0)  # Esperar a que el GPS se inicie y estabilice

        self.data.gps_on = True
        print("[SIM7600-GPS] GPS activado exitosamente!")
        return True

    def _read_loop(self):
        """Bucle de lectura de datos GPS"""
        last_info_time = 0
        last_cb_time = 0

        while self.running and self.serial and self.serial.is_open:
            try:
                now = time.time()

                # NMEA alimenta el estado continuamente; CGPSINFO queda como
                # respaldo AT cada 2 s para no bloquear la lectura.
                if now - last_info_time >= 2.0:
                    self._request_gps_info()
                    last_info_time = now

                # Leer NMEA del puerto (satelites + datos de respaldo)
                self._read_nmea()

                # Callback rapido para la interfaz y el tracker de distancia.
                if self._callback and now - last_cb_time >= 0.2:
                    self._callback(self.data)
                    last_cb_time = now

                time.sleep(0.02)

            except serial.SerialException:
                print("[SIM7600-GPS] Puerto cerrado inesperadamente")
                break
            except Exception as e:
                print(f"[SIM7600-GPS] Error en bucle: {e}")
                break

    def _send_at(self, command: str, timeout: float = 2.0) -> Optional[str]:
        """Envía un comando AT y espera respuesta"""
        if not self.serial or not self.serial.is_open:
            return None

        try:
            # Limpiar buffer de entrada
            self.serial.reset_input_buffer()

            # Enviar comando
            cmd = command.strip() + "\r\n"
            self.serial.write(cmd.encode('ascii'))
            self.serial.flush()

            # Leer respuesta
            time.sleep(0.05)  # El bucle termina al recibir OK o ERROR.
            response = b""
            end_time = time.time() + timeout

            while time.time() < end_time:
                if self.serial.in_waiting:
                    chunk = self.serial.read(self.serial.in_waiting)
                    response += chunk
                    # Si recibimos OK o ERROR, terminar
                    if b"OK" in response or b"ERROR" in response:
                        break
                else:
                    time.sleep(0.05)

            try:
                resp_str = response.decode('ascii', errors='ignore').strip()
            except:
                resp_str = ""

            if "OK" in resp_str:
                return resp_str
            elif resp_str:
                print(f"[SIM7600-GPS] AT respuesta inesperada: {resp_str[:100]}")
                return resp_str
            else:
                return None

        except serial.SerialException as e:
            print(f"[SIM7600-GPS] Error enviando '{command}': {e}")
            return None

    def _request_gps_info(self):
        """Solicita AT+CGPSINFO y parsea la respuesta"""
        resp = self._send_at("AT+CGPSINFO", timeout=2.0)
        if resp is None:
            self.data.has_fix = False
            return

        # Buscar el dato en la respuesta
        match = self.RE_CGPSINFO.search(resp)
        if match:
            try:
                lat_raw = match.group(1)
                lat_dir = match.group(2)
                lon_raw = match.group(3)
                lon_dir = match.group(4)
                date_str = match.group(5)
                time_str = match.group(6)
                alt_str = match.group(7)
                speed_str = match.group(8)
                track_str = match.group(9)

                lat_val = float(lat_raw) if lat_raw else 0.0
                lon_val = float(lon_raw) if lon_raw else 0.0
                alt_val = float(alt_str) if alt_str else 0.0
                speed_val = float(speed_str) if speed_str else 0.0
                track_val = float(track_str) if track_str else 0.0
                speed_kmh_val = speed_val * 1.852  # CGPSINFO devuelve knots

                with self.lock:
                    self.data.latitude = lat_val
                    self.data.lat_direction = lat_dir
                    self.data.longitude = lon_val
                    self.data.lon_direction = lon_dir
                    self.data.date = date_str
                    self.data.time = time_str
                    self.data.altitude = alt_val
                    self.data.speed_kmh = speed_kmh_val
                    self.data.track_angle = track_val
                    self.data.has_fix = True
                    self.data.received_at = time.time()

                # NMEA/GSV ya entrega satelites; AT queda como respaldo lento.
                if time.monotonic() - self._last_satellite_request >= 10.0:
                    self._request_satellites()
                    self._last_satellite_request = time.monotonic()

                lat_dd, lon_dd = self.data.get_coordinates_decimal()
                print(f"[SIM7600-GPS] Posicion: {lat_dd:.6f}, {lon_dd:.6f} | "
                      f"Alt:{alt_val:.1f}m Vel:{speed_val:.1f}km/h", flush=True)

                # Callback inmediato con datos frescos
                if self._callback:
                    self._callback(self.data)

            except (ValueError, IndexError) as e:
                print(f"[SIM7600-GPS] Error parseando CGPSINFO: {e}")
                self.data.has_fix = False
        else:
            # No hay fix todavía
            if self.data.has_fix:
                print("[SIM7600-GPS] Perdida de señal GPS...")
            self.data.has_fix = False

    def _request_satellites(self):
        """Pide cantidad de satélites visibles"""
        resp = self._send_at("AT+CGPSSTATUS?", timeout=1.0)
        if resp:
            match = self.RE_CGPSSTATUS.search(resp)
            if match:
                status = match.group(1)
                # Intentar extraer número de satélites
                try:
                    # Algunas respuestas: "GPS Not Fixed" o "Location 3D (12)"
                    sats_match = re.search(r'\((\d+)\)', status)
                    if sats_match:
                        self.data.num_satellites = int(sats_match.group(1))
                except:
                    pass

    def _read_nmea(self):
        """Lee tramas NMEA del puerto NMEA (/dev/ttyUSB1)."""
        # Abrir puerto NMEA si no está abierto
        if not self.nmea_serial or not self.nmea_serial.is_open:
            try:
                self.nmea_serial = serial.Serial(
                    port=self.nmea_port,
                    baudrate=self.baudrate,
                    timeout=0.5,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                )
                print(f"[SIM7600-GPS] Puerto NMEA {self.nmea_port} abierto")
            except serial.SerialException as e:
                if self.nmea_serial:
                    try:
                        self.nmea_serial.close()
                    except:
                        pass
                    self.nmea_serial = None
                return

        try:
            while self.nmea_serial.in_waiting > 0:
                line = self.nmea_serial.readline()
                if not line:
                    break

                try:
                    line_str = line.decode('ascii', errors='ignore').strip()
                except:
                    continue

                if line_str.startswith("$GPGGA") or line_str.startswith("$GNGGA"):
                    self._parse_nmea_gga(line_str)
                elif line_str.startswith("$GPGSV") or line_str.startswith("$GNGSV"):
                    self._parse_nmea_gsv(line_str)
                elif line_str.startswith("$GPRMC") or line_str.startswith("$GNRMC"):
                    self._parse_nmea_rmc(line_str)

        except serial.SerialException:
            pass

    def _parse_nmea_gga(self, line: str):
        """$GPGGA,233602.00,1202.975644,S,07701.179459,W,1,07,0.9,142.3,M,..."""
        parts = line.split(',')
        if len(parts) < 10:
            return

        try:
            with self.lock:
                if parts[2] and parts[4]:
                    self.data.latitude = float(parts[2]) if parts[2] else 0.0
                    self.data.lat_direction = parts[3]
                    self.data.longitude = float(parts[4]) if parts[4] else 0.0
                    self.data.lon_direction = parts[5]
                self.data.num_satellites = int(parts[7]) if parts[7] else 0
                self.data.altitude = float(parts[9]) if parts[9] else 0.0
                self.data.has_fix = int(parts[6]) > 0 if parts[6] else False
                self.data.received_at = time.time()
        except (ValueError, IndexError):
            pass
    
    def _parse_nmea_gsv(self, line: str):
        """$GPGSV,3,1,12,10,34,008,22,18,45,163,37,..."""
        parts = line.split(',')
        if len(parts) >= 4:
            try:
                sats_in_view = int(parts[3]) if parts[3] else 0
                with self.lock:
                    self.data.num_satellites = max(self.data.num_satellites, sats_in_view)
            except (ValueError, IndexError):
                pass

    def _parse_nmea_rmc(self, line: str):
        """$GPRMC,123456.00,A,4809.1234,N,01131.5678,E,30.5,220.3,150626,..."""
        parts = line.split(',')
        if len(parts) < 9:
            return
        try:
            with self.lock:
                status = parts[2] if len(parts) > 2 else "V"
                self.data.has_fix = (status == "A")
                if parts[3] and parts[5]:
                    self.data.latitude = float(parts[3]) if parts[3] else 0.0
                    self.data.lat_direction = parts[4]
                    self.data.longitude = float(parts[5]) if parts[5] else 0.0
                    self.data.lon_direction = parts[6]
                speed_knots = float(parts[7]) if parts[7] else 0.0
                self.data.speed_kmh = speed_knots * 1.852
                self.data.track_angle = float(parts[8]) if parts[8] else 0.0
                self.data.received_at = time.time()
        except (ValueError, IndexError):
            pass


# ═══════════════════════════════════════════════════════
#  TEST RÁPIDO
# ═══════════════════════════════════════════════════════
if __name__ == "__main__":
    import sys

    def on_gps(data):
        print(f"\r{data}", end="", flush=True)

    # Determinar puerto AT
    port = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyUSB2"
    print(f"Usando puerto: {port}")
    print("Presiona Ctrl+C para salir")

    gps = SIM7600GPS(at_port=port, baudrate=115200, auto_start=True)
    gps.set_callback(on_gps)

    try:
        gps.start()
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nDeteniendo...")
        gps.stop()
