# HDMI GPS Dashboard and Media Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Migrate MotoMami from the dual ST7789 layout to a proportional HDMI dashboard while keeping GPS, MQTT, Doom, music, video, USB media and OTA usable.

**Architecture:** Keep a logical UI canvas independent from the physical output. The HDMI backend will aspect-fit the logical canvas into the detected framebuffer, preserving proportions and adding letterbox bars instead of stretching. GPS and MQTT remain separate state producers; a dashboard app consumes both snapshots and never opens a second MQTT or serial connection.

**Tech Stack:** Python 3.14, Pillow, Linux framebuffer mmap, paho-mqtt, pyserial, ffmpeg/ffplay, ESP-IDF 6 / PlatformIO, SIM7600 NMEA + AT.

---

## Phase 0: Velocimeter low-speed fix

**Files:**
- Modify: `Motomami-esp32/Motomami-velocimetro-temperatura-esp32c6/src/main.c`

1. Store the pulse period in `int64_t`, not `uint32_t`; hand rotation can exceed 4.29 seconds between pulses.
2. Keep the 1 ms state filter and minimum pulse gap.
3. Publish `dt` for field diagnosis.
4. Build with `pio run`.
5. Upload with the existing HTTP OTA endpoint when `Motomami-net` is available.
6. Verify `speed=0` while stopped, then verify a slow hand rotation produces a small speed instead of a stale high value.

## Phase 1: Display backend abstraction

**Files:**
- Modify: `src/config_loader.py`
- Modify: `src/libs/fb_display.py`
- Modify: `config.ini.example`
- Modify: `deploy/motomami.service`

1. Add `display.mode=dual|hdmi`, `display.hdmi_fb`, `display.hdmi_width`, and `display.hdmi_height`.
2. Detect framebuffer width, height, bits-per-pixel and line stride from sysfs/ioctl.
3. Add a single HDMI output path that composites the logical image and writes one framebuffer.
4. Use aspect-fit scaling. For the current `640x240` logical canvas on `1280x800`, render at `1280x480` with 160 px top and bottom bars; never stretch to `1280x800`.
5. Support RGB565 and 32-bit XRGB/RGB888 output; do not assume every framebuffer is 16-bit.
6. Keep the dual ST7789 path unchanged as the default until HDMI is verified.
7. Verify with `fbset`, `/sys/class/graphics/fb*/virtual_size`, `bits_per_pixel`, DRM HDMI status and a color test image.

## Phase 2: GPS distance and faster updates

**Files:**
- Modify: `src/core/state.py`
- Modify: `src/core/gps_service.py`
- Modify: `src/drivers/sim7600_gps.py`
- Modify: `src/config_loader.py`
- Modify: `config.ini.example`
- Modify: `src/core/telemetria_service.py`

1. Add `gps_trip_distance_m` and persistent `gps_total_distance_m` to `GPSState`.
2. Add a Haversine tracker fed only by valid, non-cached fixes.
3. Reject duplicate points, movements below 2 m and impossible jumps; persist atomically every 50 m or 60 s.
4. Preserve Hall distance fields separately as `wheel_distance_m`/`wheel_odometer_km` at the API boundary; keep compatibility aliases during migration.
5. Make NMEA the fast source and use `AT+CGPSINFO` as a slower fallback. Poll satellites from NMEA/GSV; do not issue `AT+CGPSSTATUS?` on every fix.
6. Replace the fixed 300 ms AT sleep with terminator-based reads and keep one reader per serial port.
7. Do not change baudrate until both AT and NMEA ports are configured and verified independently.
8. Add GPS distance and wheel metrics to ThingsBoard telemetry.
9. Test the tracker with fixed coordinates, duplicate fixes, a short valid movement and an impossible jump.

## Phase 3: GPS plus MQTT dashboard

**Files:**
- Modify: `src/apps/gps_display_app.py`
- Create or modify: `src/apps/ride_dashboard_app.py`
- Modify: `src/main.py`
- Modify: `src/apps/main_menu.py`
- Modify: `src/libs/theme.py`

1. Keep one dashboard entry as the default app on startup when `display.mode=hdmi`.
2. Show GPS speed, Hall speed, GPS altitude, satellite count, GPS trip/total distance, wheel distance/odometer and MQTT light/brake states.
3. Clearly label GPS and wheel values; never silently substitute one source for the other.
4. Show FIX/CACHE/NO FIX and MQTT ONLINE/STALE/OFF states.
5. Use theme-derived colors and larger HDMI typography; preserve the compact dual-screen renderer.
6. Keep UP/DOWN zoom and BACK behavior available with GPIO/Xbox controls.

## Phase 4: USB media discovery

**Files:**
- Create: `src/libs/media_sources.py`
- Modify: `src/config_loader.py`
- Modify: `src/apps/music_player_app.py`
- Modify: `src/apps/video_player_app.py`
- Modify: `deploy/motomami.service`
- Modify: `config.ini.example`

1. Discover mounted removable filesystems using `findmnt`/`lsblk` without treating serial ports as media.
2. Prefer configured music/movie folders, then add mounted USB roots under a visible `USB` source.
3. Keep directory traversal bounded and handle unplugging without crashing the browser.
4. Optionally mount unmounted USB partitions through `udisksctl` only when available; never block startup waiting for a USB device.
5. Add source refresh from the browser using the existing button controls.
6. Test with no USB, one USB, unplug during browsing, and duplicate filenames.

## Phase 5: HDMI-safe Doom, music and video

**Files:**
- Modify: `src/apps/doom_app.py`
- Modify: `src/apps/music_player_app.py`
- Modify: `src/apps/video_player_app.py`

1. Route all output through `FbDisplay`; remove direct `_get_fb1()`/`_get_fb2()` writes in HDMI mode.
2. Keep Doom's `320x200` aspect ratio with letterbox bars, then let the display backend scale it proportionally.
3. Preserve video aspect ratio with ffmpeg `scale` plus `pad`, rather than forcing every source to `320x240`.
4. Use a single composed canvas for video plus controls on HDMI.
5. Keep the existing dual-screen layout as the default fallback.
6. Verify Doom, 16:9 video, 4:3 video, music browser and USB source navigation on both backends.

## Deployment sequence

1. Commit and push source changes to `MarioAntizana1/Motomami-unificado`.
2. Deploy Python files to `/home/motomami/moto/` and restart `motomami`.
3. Build ESP firmware and validate the image with `esptool image_info`.
4. Download the binary through the RPi-accessible HTTP path and POST it to the ESP OTA endpoint.
5. Verify MQTT status, sensor data, wheel metrics and OTA endpoint before moving to the next phase.
