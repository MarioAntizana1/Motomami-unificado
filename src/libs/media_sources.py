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


def _removable_parts() -> list[dict]:
    """Particiones en dispositivos removibles (RM=1), montadas o no."""
    try:
        result = subprocess.run(
            ["lsblk", "-J", "-o", "PATH,TYPE,RM,MOUNTPOINT,LABEL,FSTYPE"],
            capture_output=True, text=True, timeout=2,
        )
        data = json.loads(result.stdout) if result.returncode == 0 else {}
    except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError):
        return []

    parts = []
    for node in data.get("blockdevices", []):
        if node.get("rm") not in (True, "1", 1):
            continue
        children = node.get("children") or []
        for part in children if children else [node]:
            if part.get("type") == "part" and part.get("path"):
                parts.append(part)
    return parts


def _sanitize(label: str) -> str:
    return "".join(c for c in label if c.isalnum() or c in "-_") or "usb"


def _ensure_usb_mounted() -> list[MediaSource]:
    """Monta particiones USB removibles no montadas (el servicio corre como root)
    y devuelve las fuentes disponibles."""
    sources = []
    for part in _removable_parts():
        mount = part.get("mountpoint") or ""
        path = part.get("path")
        label = part.get("label") or "pendrive"
        if not mount:
            target = f"/mnt/motomami_{_sanitize(label)}"
            if not os.path.isdir(target):
                try:
                    os.makedirs(target, exist_ok=True)
                except OSError:
                    continue
            mount = subprocess.run(
                ["mount", path, target], capture_output=True, text=True, timeout=5
            )
            if mount.returncode != 0:
                print(f"[MediaSources] No se pudo montar {path}: {mount.stderr.strip()}") if mount.stderr else None
                continue
            mount = target
        if os.path.isdir(mount):
            sources.append(MediaSource(mount, f"USB: {label}", True))
    return sources


def discover_media_sources(preferred: str, kind: str) -> list[MediaSource]:
    """Devuelve fuente configurada primero y luego USBs (montadas o montables) sin duplicar."""
    sources = []
    if preferred and os.path.isdir(preferred):
        sources.append(MediaSource(preferred, f"LOCAL: {kind}"))

    seen = {os.path.realpath(s.path) for s in sources}
    for source in _ensure_usb_mounted():
        real = os.path.realpath(source.path)
        if real not in seen:
            sources.append(source)
            seen.add(real)
    return sources
