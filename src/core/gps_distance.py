"""Distancia GPS con filtro de saltos y persistencia atomica."""
from __future__ import annotations

import json
import math
import os
import tempfile
import time
from pathlib import Path


class GPSDistanceTracker:
    """Acumula distancia solo entre fixes validos y no cacheados."""

    EARTH_RADIUS_M = 6_371_000.0

    def __init__(
        self,
        path: str,
        min_segment_m: float = 2.0,
        save_segment_m: float = 50.0,
        save_interval_s: float = 60.0,
    ):
        self.path = Path(path)
        self.min_segment_m = min_segment_m
        self.save_segment_m = save_segment_m
        self.save_interval_s = save_interval_s
        self.trip_distance_m = 0.0
        self.total_distance_m = 0.0
        self._dirty_m = 0.0
        self._last_save = time.time()
        self._last_point: tuple[float, float] | None = None
        self._last_time = 0.0
        self._load()

    @staticmethod
    def _haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
        lat1, lon1 = map(math.radians, a)
        lat2, lon2 = map(math.radians, b)
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        h = math.sin(dlat / 2) ** 2
        h += math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        return 2.0 * GPSDistanceTracker.EARTH_RADIUS_M * math.asin(math.sqrt(min(1.0, h)))

    def _load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.total_distance_m = max(0.0, float(data.get("total_distance_m", 0.0)))
        except (FileNotFoundError, OSError, ValueError, TypeError, json.JSONDecodeError):
            self.total_distance_m = 0.0

    def _save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(prefix="gps-distance-", suffix=".tmp", dir=self.path.parent)
            with os.fdopen(fd, "w", encoding="utf-8") as tmp:
                json.dump({"total_distance_m": round(self.total_distance_m, 3)}, tmp)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(tmp_name, self.path)
            self._dirty_m = 0.0
            self._last_save = time.time()
        except OSError:
            try:
                os.unlink(tmp_name)
            except (UnboundLocalError, OSError):
                pass

    def update(self, data) -> tuple[float, float]:
        if not bool(data.has_fix):
            return self.trip_distance_m, self.total_distance_m

        lat, lon = data.get_coordinates_decimal()
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            return self.trip_distance_m, self.total_distance_m
        if lat == 0.0 and lon == 0.0:
            return self.trip_distance_m, self.total_distance_m

        now = float(data.received_at or time.time())
        point = (lat, lon)
        if self._last_point is not None and now > self._last_time:
            segment = self._haversine_m(self._last_point, point)
            elapsed = now - self._last_time
            # 80 m/s is a generous upper bound for this motorcycle; the
            # absolute floor allows a delayed callback without rejecting it.
            max_segment = max(200.0, elapsed * 80.0 + 20.0)
            if self.min_segment_m <= segment <= max_segment:
                self.trip_distance_m += segment
                self.total_distance_m += segment
                self._dirty_m += segment

        self._last_point = point
        self._last_time = now
        if self._dirty_m >= self.save_segment_m or time.time() - self._last_save >= self.save_interval_s:
            self._save()
        return self.trip_distance_m, self.total_distance_m
