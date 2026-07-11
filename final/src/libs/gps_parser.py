#!/usr/bin/env python3
"""
gps_parser.py - Parser de tramas NMEA del SIM7600-G
Lee desde /dev/ttyUSB2 y parsea GPGGA, GPRMC, GPGSV, GPGSA, GPVTG
"""

import re
import time
import threading
from typing import Optional, Dict, Any
from dataclasses import dataclass


@dataclass
class GPSData:
    """Datos completos del GPS"""
    # GGA
    timestamp: str = ""          # HHMMSS.SS
    latitude: float = 0.0
    lat_direction: str = "N"
    longitude: float = 0.0
    lon_direction: str = "W"
    fix_quality: int = 0         # 0=no fix, 1=GPS, 2=DGPS
    num_satellites: int = 0
    hdop: float = 0.0            # Precision horizontal
    altitude: float = 0.0        # Metros
    altitude_unit: str = "M"
    geoid_separation: float = 0.0
    geoid_unit: str = "M"

    # RMC
    rmc_timestamp: str = ""
    rmc_date: str = ""            # DDMMYY
    status: str = "V"            # A=active, V=void
    speed_knots: float = 0.0
    speed_kmh: float = 0.0
    track_angle: float = 0.0     # Grados true
    magnetic_variation: float = 0.0
    mag_var_direction: str = ""

    # GSV - Satelites en vista
    satellites_in_view: int = 0
    satellites: list = None      # Lista de dicts con PRN, elev, azim, SNR

    # GSA
    fix_type: int = 1            # 1=no fix, 2=2D, 3=3D
    pdop: float = 0.0
    hdop_gsa: float = 0.0
    vdop: float = 0.0

    # VTG
    vtg_track_true: float = 0.0
    vtg_track_magnetic: float = 0.0
    vtg_speed_knots: float = 0.0
    vtg_speed_kmh: float = 0.0

    def has_fix(self) -> bool:
        return self.fix_quality > 0 or self.status == 'A'

    def get_coordinates_dd(self) -> tuple:
        """Retorna (lat, lon) en grados decimales"""
        return (self.latitude, self.longitude)

    def get_coordinates_decimal(self) -> tuple:
        """Convierte NMEA (DDMM.MMMM) a grados decimales"""
        lat_dd = self._nmea_to_decimal(self.latitude, self.lat_direction)
        lon_dd = self._nmea_to_decimal(self.longitude, self.lon_direction)
        return (lat_dd, lon_dd)

    @staticmethod
    def _nmea_to_decimal(nmea_coord: float, direction: str) -> float:
        """Convierte formato NMEA DDMM.MMMM a DD.DDDDD"""
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
        return (f"GPS: Fix={'SI' if self.has_fix() else 'NO'} | "
                f"Lat={lat:.6f}° | Lon={lon:.6f}° | "
                f"Alt={self.altitude:.1f}m | "
                f"Vel={self.speed_kmh:.1f}km/h | "
                f"Sats={self.num_satellites}/{self.satellites_in_view}")


class GPSParser:
    """
    Lector de GPS desde dispositivo serial (/dev/ttyUSB2).
    Corre en un hilo separado y actualiza datos periódicamente.
    """

    def __init__(self, port: str = "/dev/ttyUSB2", baudrate: int = 115200):
        self.port = port
        self.baudrate = baudrate
        self.data = GPSData()
        self.running = False
        self.thread = None
        self.serial = None
        self.lock = threading.Lock()
        self._callback = None

    def set_callback(self, callback):
        """Callback que se llama con cada actualización de GPS"""
        self._callback = callback

    def start(self):
        """Inicia el hilo de lectura de GPS"""
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._reader_loop, daemon=True)
        self.thread.start()
        print(f"[GPS] Iniciando lectura en {self.port} @ {self.baudrate} baud")

    def stop(self):
        """Detiene el hilo de lectura"""
        self.running = False
        if self.serial:
            try:
                self.serial.close()
            except:
                pass
        print("[GPS] Detenido")

    def get_data(self) -> GPSData:
        """Obtiene los datos actuales (thread-safe)"""
        with self.lock:
            return self.data

    def _reader_loop(self):
        """Bucle principal de lectura"""
        import serial

        while self.running:
            try:
                if self.serial is None or not self.serial.is_open:
                    self.serial = serial.Serial(
                        self.port,
                        self.baudrate,
                        timeout=1.0
                    )
                    print(f"[GPS] Puerto {self.port} abierto")

                line = self.serial.readline()
                if not line:
                    continue

                try:
                    line_str = line.decode('ascii', errors='ignore').strip()
                except:
                    continue

                if not line_str:
                    continue

                self._parse_line(line_str)

            except serial.SerialException as e:
                print(f"[GPS] Error serial: {e}")
                time.sleep(2)
            except Exception as e:
                print(f"[GPS] Error: {e}")
                time.sleep(1)

    def _parse_line(self, line: str):
        """Parsea una línea NMEA"""
        if not line.startswith('$'):
            return

        if line.startswith('$GPGGA') or line.startswith('$GNGGA'):
            self._parse_gga(line)
        elif line.startswith('$GPRMC') or line.startswith('$GNRMC'):
            self._parse_rmc(line)
        elif line.startswith('$GPGSV') or line.startswith('$GNGSV'):
            self._parse_gsv(line)
        elif line.startswith('$GPGSA') or line.startswith('$GNGSA'):
            self._parse_gsa(line)
        elif line.startswith('$GPVTG') or line.startswith('$GNVTG'):
            self._parse_vtg(line)

    def _parse_gga(self, line: str):
        """$GPGGA,233602.00,1202.975644,S,07701.179459,W,1,07,0.9,142.3,M,57.0,M,,*67"""
        parts = line.split(',')
        if len(parts) < 14:
            return

        with self.lock:
            try:
                self.data.timestamp = parts[1]
                self.data.latitude = float(parts[2]) if parts[2] else 0.0
                self.data.lat_direction = parts[3]
                self.data.longitude = float(parts[4]) if parts[4] else 0.0
                self.data.lon_direction = parts[5]
                self.data.fix_quality = int(parts[6]) if parts[6] else 0
                self.data.num_satellites = int(parts[7]) if parts[7] else 0
                self.data.hdop = float(parts[8]) if parts[8] else 0.0
                self.data.altitude = float(parts[9]) if parts[9] else 0.0
                self.data.altitude_unit = parts[10]
                self.data.geoid_separation = float(parts[11]) if parts[11] else 0.0
                self.data.geoid_unit = parts[12]
            except (ValueError, IndexError):
                pass

        if self._callback:
            self._callback(self.data)

    def _parse_rmc(self, line: str):
        """$GPRMC,233602.00,A,1202.975644,S,07701.179459,W,0.0,,150626,0.9,W,A*05"""
        parts = line.split(',')
        if len(parts) < 12:
            return

        with self.lock:
            try:
                self.data.rmc_timestamp = parts[1]
                self.data.status = parts[2]
                if parts[3]:
                    self.data.latitude = float(parts[3])
                    self.data.lat_direction = parts[4]
                if parts[5]:
                    self.data.longitude = float(parts[5])
                    self.data.lon_direction = parts[6]
                self.data.speed_knots = float(parts[7]) if parts[7] else 0.0
                self.data.speed_kmh = self.data.speed_knots * 1.852
                self.data.track_angle = float(parts[8]) if parts[8] else 0.0
                self.data.rmc_date = parts[9] if len(parts) > 9 and parts[9] else ""
                self.data.magnetic_variation = float(parts[10]) if len(parts) > 10 and parts[10] else 0.0
                self.data.mag_var_direction = parts[11] if len(parts) > 11 else ""
            except (ValueError, IndexError):
                pass

        if self._callback:
            self._callback(self.data)

    def _parse_gsv(self, line: str):
        """$GPGSV,3,1,12,10,34,008,22,18,45,163,37,23,50,059,43,25,34,057,32,1*6F"""
        parts = line.split(',')
        if len(parts) < 4:
            return

        num_sentences = int(parts[1]) if parts[1] else 0
        sentence_num = int(parts[2]) if parts[2] else 0
        sats_in_view = int(parts[3]) if parts[3] else 0

        # 4 satelites por trama, empezando desde index 4
        satellites = []
        for i in range(4):
            base = 4 + (i * 4)
            if base + 3 < len(parts):
                try:
                    prn = parts[base]
                    elevation = parts[base + 1]
                    azimuth = parts[base + 2]
                    snr = parts[base + 3]
                    if prn and elevation:
                        satellites.append({
                            'prn': prn,
                            'elevation': int(elevation) if elevation else 0,
                            'azimuth': int(azimuth) if azimuth else 0,
                            'snr': int(snr) if snr else 0,
                        })
                except (ValueError, IndexError):
                    continue

        with self.lock:
            self.data.satellites_in_view = sats_in_view
            if not self.data.satellites:
                self.data.satellites = []
            # Para multi-trama, acumulamos
            if sentence_num == 1:
                self.data.satellites = satellites
            else:
                self.data.satellites.extend(satellites)

    def _parse_gsa(self, line: str):
        """$GPGSA,A,2,18,23,25,26,27,31,32,,,,,,1.2,0.9,0.8*3C"""
        parts = line.split(',')
        if len(parts) < 17:
            return

        with self.lock:
            try:
                self.data.fix_type = int(parts[2]) if parts[2] else 1
                self.data.pdop = float(parts[15]) if parts[15] else 0.0
                self.data.hdop_gsa = float(parts[16]) if parts[16] else 0.0
                self.data.vdop = float(parts[17]) if len(parts) > 17 and parts[17] else 0.0
            except (ValueError, IndexError):
                pass

    def _parse_vtg(self, line: str):
        """$GPVTG,,T,0.9,M,0.0,N,0.0,K,A*04"""
        parts = line.split(',')
        if len(parts) < 9:
            return

        with self.lock:
            try:
                self.data.vtg_track_true = float(parts[1]) if parts[1] else 0.0
                self.data.vtg_track_magnetic = float(parts[3]) if parts[3] else 0.0
                self.data.vtg_speed_knots = float(parts[5]) if parts[5] else 0.0
                self.data.vtg_speed_kmh = float(parts[7]) if parts[7] else 0.0
            except (ValueError, IndexError):
                pass


# === TEST ===
if __name__ == "__main__":
    import time

    def on_update(data):
        print(f"\r{data}", end="", flush=True)

    gps = GPSParser("/dev/ttyUSB2", 115200)
    gps.set_callback(on_update)
    gps.start()

    try:
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n[GPS] Deteniendo...")
        gps.stop()
