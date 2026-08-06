"""Descubrimiento liviano de carpetas locales y memorias USB montadas."""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class MediaSource:
    path: str
    label: str
    removable: bool = False


def _walk_lsblk(nodes):
    for node in nodes or []:
        mount = node.get("mountpoint")
        if mount and mount != "/" and os.path.isdir(mount):
            yield node
        yield from _walk_lsblk(node.get("children"))


def _mounted_usb_sources() -> list[MediaSource]:
    try:
        result = subprocess.run(
            ["lsblk", "-J", "-o", "PATH,TYPE,RM,MOUNTPOINT,LABEL,FSTYPE"],
            capture_output=True, text=True, timeout=2,
        )
        data = json.loads(result.stdout) if result.returncode == 0 else {}
    except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError):
        return []

    sources = []
    for node in _walk_lsblk(data.get("blockdevices", [])):
        mount = node.get("mountpoint")
        removable = str(node.get("rm", "0")) == "1"
        if not removable and not any(mount.startswith(p) for p in ("/media/", "/run/media/", "/mnt/")):
            continue
        label = node.get("label") or os.path.basename(mount.rstrip("/")) or "USB"
        sources.append(MediaSource(mount, f"USB: {label}", True))
    return sources


def discover_media_sources(preferred: str, kind: str) -> list[MediaSource]:
    """Retorna fuente configurada primero y luego USB montadas sin duplicar."""
    sources = []
    if preferred and os.path.isdir(preferred):
        sources.append(MediaSource(preferred, f"LOCAL: {kind}"))

    seen = {os.path.realpath(s.path) for s in sources}
    for source in _mounted_usb_sources():
        real = os.path.realpath(source.path)
        if real not in seen:
            sources.append(source)
            seen.add(real)
    return sources
