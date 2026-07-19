---
name: motomami-sftp
description: "SFTP file manager para RPi via paramiko: ls, tree, get, put, sync, find, cat, edit, info, du, mv, rm, mkdir."
risk: safe
source: personal
date_added: "2026-07-17"
---

# MotoMami SFTP — File Manager Remoto

## Purpose

Transferir, sincronizar, inspeccionar y editar archivos en la Raspberry Pi vía SFTP desde Windows. Reemplaza la limitación del shell PowerShell de opencode con un file manager completo usando paramiko.

## Use this when

- Listar directorios remotos (`ls`, `tree`)
- Descargar/subir archivos (`get`, `put`)
- Sincronizar código local con la RPi (`sync`)
- Ver contenido de archivos remotos (`cat`)
- Editar archivos remotos (`edit` → modificar local → `put`)
- Inspeccionar sistema de archivos remoto (`info`, `du`, `find`)
- Mover, renombrar, eliminar o crear directorios (`mv`, `rm`, `mkdir`)

## Location

```powershell
python tools/sftp_mgr.py <comando> [argumentos]
```

El script está en `tools/sftp_mgr.py` del workspace. Requiere Python 3.10+ con `paramiko`.

## Connection

Credenciales en `opencode.json`:
- **Host**: `192.168.31.195`
- **User**: `motomami`
- **Password**: `Ktiarts123*/*`
- **Port**: 22

La conexión se abre/cierra en cada comando. No requiere setup SSH key.

## Commands

### `ls [remotedir]`
Listar contenido de directorio remoto.
```powershell
python tools/sftp_mgr.py ls /home/motomami/moto
python tools/sftp_mgr.py ls /home/motomami/moto/src/apps
```

### `tree [remotedir] [--depth N]`
Árbol de directorios (default depth=3).
```powershell
python tools/sftp_mgr.py tree /home/motomami/moto --depth 2
python tools/sftp_mgr.py tree /home/motomami/moto/src
```

### `get <remotefile> [localfile]`
Descargar archivo. Si no se especifica localfile, se usa el mismo nombre.
```powershell
python tools/sftp_mgr.py get /home/motomami/moto/src/main.py
python tools/sftp_mgr.py get /home/motomami/moto/src/main.py backup_main.py
```

### `put <localfile> [remotefile]`
Subir archivo. Si no se especifica remotefile, se usa el mismo nombre.
```powershell
python tools/sftp_mgr.py put src/main.py
python tools/sftp_mgr.py put src/drivers/sim7600_gps.py /home/motomami/moto/src/drivers/sim7600_gps.py
```

### `get -r <remotedir> [localdir]`
Descargar directorio recursivamente.
```powershell
python tools/sftp_mgr.py get -r /home/motomami/moto/src backup_src
```

### `put -r <localdir> [remotedir]`
Subir directorio recursivamente.
```powershell
python tools/sftp_mgr.py put -r src /home/motomami/moto/src
```

### `sync <localdir> <remotedir> [direction]`
Sincronizar directorios comparando tamaño y timestamp. Direction: `up` (local→remote), `down` (remote→local), o ambos (default).
```powershell
python tools/sftp_mgr.py sync src /home/motomami/moto/src up
python tools/sftp_mgr.py sync src /home/motomami/moto/src down
python tools/sftp_mgr.py sync src /home/motomami/moto/src
```

### `find <remotedir> <pattern>`
Buscar archivos por glob pattern.
```powershell
python tools/sftp_mgr.py find /home/motomami/moto "*.py"
python tools/sftp_mgr.py find /home/motomami/moto "*.wad"
```

### `info <remotepath>`
Información detallada (tipo, tamaño, fecha, permisos, uid/gid).
```powershell
python tools/sftp_mgr.py info /home/motomami/moto/src/main.py
python tools/sftp_mgr.py info /home/motomami/moto
```

### `cat <remotefile>`
Ver contenido de archivo remoto en stdout.
```powershell
python tools/sftp_mgr.py cat /home/motomami/moto/src/main.py
python tools/sftp_mgr.py cat /home/motomami/moto/config.ini
```

### `edit <remotefile>`
Descargar archivo a un temp local, mostrar contenido en stdout, e imprimir instrucciones para modificarlo y subirlo de vuelta.
```powershell
python tools/sftp_mgr.py edit /home/motomami/moto/src/core/state.py
```
Luego:
```powershell
# Modificar el archivo local (el agente extrae el path del output de edit)
python tools/sftp_mgr.py put <local_temp_path> /home/motomami/moto/src/core/state.py
```

### `du [remotedir]`
Uso de disco del directorio (tamaño total, archivos, directorios).
```powershell
python tools/sftp_mgr.py du /home/motomami/moto
```

### `mv <remotefrom> <remoteto>`
Mover o renombrar archivo/directorio remoto.
```powershell
python tools/sftp_mgr.py mv /home/motomami/moto/tmp/old.txt /home/motomami/moto/tmp/new.txt
```

### `rm <remotepath>`
Eliminar archivo o directorio vacío.
```powershell
python tools/sftp_mgr.py rm /home/motomami/moto/tmp/test.txt
```

### `mkdir <remotedir>`
Crear directorio remoto (incluyendo padres).
```powershell
python tools/sftp_mgr.py mkdir /home/motomami/moto/logs
python tools/sftp_mgr.py mkdir /home/motomami/moto/src/new_module
```

## Typical Workflows

### Sync code from Windows to RPi
```powershell
python tools/sftp_mgr.py sync src /home/motomami/moto/src up
```

### Edit a remote file
```powershell
python tools/sftp_mgr.py edit /home/motomami/moto/src/main.py
# → output muestra contenido y ruta del temp file
python tools/sftp_mgr.py put C:\Users\wenup\AppData\Local\Temp\tmpXXXXXX.py /home/motomami/moto/src/main.py
```

### Backup a directory
```powershell
python tools/sftp_mgr.py get -r /home/motomami/moto/src C:\backups\moto-src
```

### Inspect remote project structure
```powershell
python tools/sftp_mgr.py tree /home/motomami/moto/src --depth 3
python tools/sftp_mgr.py du /home/motomami/moto
```

## Notes

- Todos los paths remotos usan `/` (Linux). Paths locales usan `\` (Windows), el script normaliza.
- Permisos de archivo se preservan en `put`/`get`.
- La conexión se autentica con password (no SSH key).
- Si un comando falla por timeout (default 10s), reintentar con `--timeout 30` (no implementado aún, editar `SFTP_TIMEOUT` en `tools/sftp_mgr.py` línea ~25).
- Para archivos muy grandes (>100MB), usar `get`/`put` directo, no `sync` (que compara uno por uno).

## Key Files

| File | Role |
|------|------|
| `tools/sftp_mgr.py` | Script SFTP file manager (Python + paramiko) |
| `opencode.json` | Credenciales SSH (host, user, password) |
| `.agents/skills/motomami-sftp/SKILL.md` | Esta skill |
