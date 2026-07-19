#!/usr/bin/env python3
"""SFTP File Manager — como WinSCP para el agente.

Uso desde el agente:
  python tools/sftp_mgr.py ls [remotedir]
  python tools/sftp_mgr.py get <remotefile> [localfile]
  python tools/sftp_mgr.py put <localfile> [remotefile]
  python tools/sftp_mgr.py tree [remotedir]
  python tools/sftp_mgr.py info <remotepath>
  python tools/sftp_mgr.py find <remotedir> <pattern>
  python tools/sftp_mgr.py cat <remotefile>
  python tools/sftp_mgr.py edit <remotefile>
  python tools/sftp_mgr.py sync <localdir> <remotedir> [up|down]
  python tools/sftp_mgr.py du [remotedir]
  python tools/sftp_mgr.py mv <remotefrom> <remoteto>
  python tools/sftp_mgr.py rm <remotefile>
  python tools/sftp_mgr.py mkdir <remotedir>
"""

import argparse
import fnmatch
import os
import stat as stat_m
import sys
import tempfile
import time
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.upper() not in ("UTF-8", "UTF8"):
    sys.stdout.reconfigure(encoding="utf-8")

import paramiko

HOST = "192.168.31.195"
PORT = 22
USER = "motomami"
PASSWORD = "Ktiarts123*/*"


class SFTPMgr:
    def __init__(self):
        self._transport = None
        self._sftp = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.close()

    def connect(self):
        self._transport = paramiko.Transport((HOST, PORT))
        self._transport.connect(username=USER, password=PASSWORD)
        self._sftp = paramiko.SFTPClient.from_transport(self._transport)

    def close(self):
        if self._sftp:
            self._sftp.close()
        if self._transport:
            self._transport.close()

    # ---- ls ----
    def ls(self, path="."):
        path = path or "."
        items = []
        for f in self._sftp.listdir_attr(path):
            is_dir = stat_m.S_ISDIR(f.st_mode)
            size = f.st_size
            mtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(f.st_mtime))
            name = f.filename
            if is_dir:
                name += "/"
            items.append((is_dir, size, mtime, name))
        return items

    def ls_text(self, path="."):
        items = self.ls(path)
        if not items:
            return "(empty)"
        lines = []
        for is_dir, size, mtime, name in items:
            s = f"{mtime}  {size:>8,}  {name}"
            lines.append(s)
        return "\n".join(lines)

    # ---- tree ----
    def tree(self, path=".", prefix="", max_depth=3, depth=0):
        if depth > max_depth:
            return [f"{prefix}+-- ..."]
        lines = []
        items = sorted(self.ls(path), key=lambda x: (not x[0], x[3].lower()))
        for i, (is_dir, size, mtime, name) in enumerate(items):
            is_last = i == len(items) - 1
            connector = "+-- " if is_last else "|-- "
            full = f"{path}/{name}" if path not in (".", "") else name
            if is_dir:
                name_disp = name.rstrip("/")
                lines.append(f"{prefix}{connector}{name_disp}/")
                ext = "    " if is_last else "|   "
                lines.extend(self.tree(full, prefix + ext, max_depth, depth + 1))
            else:
                lines.append(f"{prefix}{connector}{name}  ({size:,}B)")
        return lines

    def tree_text(self, path=".", max_depth=3):
        base = os.path.basename(path.rstrip("/")) or path or "."
        lines = [f"{base}/"]
        lines.extend(self.tree(path, max_depth=max_depth))
        return "\n".join(lines)

    # ---- get ----
    def get(self, remote, local=None):
        if local is None:
            local = os.path.basename(remote.rstrip("/"))
        s = os.path.getsize(local) if os.path.exists(local) else 0
        self._sftp.get(remote, local, callback=self._progress)
        print(f"\n[OK] {remote} -> {local}")
        return local

    def get_recursive(self, remote, local):
        remote = remote.rstrip("/")
        local = local.rstrip("/")
        os.makedirs(local, exist_ok=True)
        for item in self._sftp.listdir_attr(remote):
            rp = f"{remote}/{item.filename}"
            lp = f"{local}/{item.filename}"
            if stat_m.S_ISDIR(item.st_mode):
                self.get_recursive(rp, lp)
            else:
                self._sftp.get(rp, lp, callback=self._progress)
                print()

    # ---- put ----
    def put(self, local, remote=None):
        if remote is None:
            remote = os.path.basename(local)
        self._sftp.put(local, remote, callback=self._progress)
        print(f"\n[OK] {local} -> {remote}")
        return remote

    def put_recursive(self, local, remote):
        local = local.rstrip("/")
        remote = remote.rstrip("/")
        try:
            self._sftp.stat(remote)
        except FileNotFoundError:
            self._sftp.mkdir(remote)
        for item in os.listdir(local):
            lp = f"{local}/{item}"
            rp = f"{remote}/{item}"
            if os.path.isdir(lp):
                self.put_recursive(lp, rp)
            else:
                self._sftp.put(lp, rp, callback=self._progress)
                print()

    # ---- sync ----
    def sync(self, local_dir, remote_dir, direction="up", dry_run=False):
        local_dir = local_dir.rstrip("/")
        remote_dir = remote_dir.rstrip("/")
        copied = 0
        skipped = 0
        errors = 0

        local_files = {}
        for root, dirs, files in os.walk(local_dir):
            for f in files:
                fp = os.path.join(root, f)
                rel = os.path.relpath(fp, local_dir)
                local_files[rel] = (fp, os.path.getmtime(fp), os.path.getsize(fp))

        if direction == "up":
            for rel, (fp, lm, ls) in local_files.items():
                rp = f"{remote_dir}/{rel.replace(os.sep, '/')}"
                try:
                    ra = self._sftp.stat(rp)
                    rm = ra.st_mtime
                    rs = ra.st_size
                    if abs(lm - rm) < 1 and ls == rs:
                        skipped += 1
                        continue
                except FileNotFoundError:
                    pass
                if dry_run:
                    print(f"  → {rp}")
                else:
                    os.makedirs(os.path.dirname(rp), exist_ok=True)
                    self._sftp.put(fp, rp, callback=self._progress)
                    print()
                copied += 1
        else:
            for rel, (fp, lm, ls) in local_files.items():
                rp = f"{remote_dir}/{rel.replace(os.sep, '/')}"
                try:
                    ra = self._sftp.stat(rp)
                    rm = ra.st_mtime
                    rs = ra.st_size
                    if abs(lm - rm) < 1 and ls == rs:
                        skipped += 1
                        continue
                except FileNotFoundError:
                    pass
                if dry_run:
                    print(f"  ← {rp}")
                else:
                    os.makedirs(os.path.dirname(fp), exist_ok=True)
                    self._sftp.get(rp, fp, callback=self._progress)
                    print()
                copied += 1

        return copied, skipped, errors

    # ---- find ----
    def find(self, path, pattern, max_depth=10):
        path = path.rstrip("/")
        results = []
        try:
            for item in self._sftp.listdir_attr(path):
                fp = f"{path}/{item.filename}"
                if fnmatch.fnmatch(item.filename, pattern):
                    results.append(fp)
                if stat_m.S_ISDIR(item.st_mode) and max_depth > 0:
                    results.extend(self.find(fp, pattern, max_depth - 1))
        except PermissionError:
            pass
        return results

    # ---- info ----
    def info(self, path):
        try:
            a = self._sftp.stat(path)
        except FileNotFoundError:
            return f"[ERR] No existe: {path}"
        is_dir = stat_m.S_ISDIR(a.st_mode)
        lines = [
            f"Path:    {path}",
            f"Type:    {'[DIR]' if is_dir else '[FILE]'}",
            f"Size:    {a.st_size:,} bytes",
            f"Modified: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(a.st_mtime))}",
            f"Perm:    {stat_m.filemode(a.st_mode)}",
            f"UID/GID: {a.st_uid}/{a.st_gid}",
        ]
        return "\n".join(lines)

    # ---- cat ----
    def cat(self, path, max_bytes=100000):
        with self._sftp.open(path, "r") as f:
            data = f.read(max_bytes)
            if isinstance(data, bytes):
                data = data.decode("utf-8", errors="replace")
            if len(data) >= max_bytes:
                data += "\n... (truncated)"
        return data

    # ---- edit: pull → print → push ----
    def edit_pull(self, path):
        local = tempfile.NamedTemporaryFile(mode="w+", suffix=".tmp", delete=False)
        local_path = local.name
        self._sftp.get(path, local_path)
        with open(local_path, "r") as f:
            content = f.read()
        return local_path, content

    def edit_push(self, local_path, remote_path):
        self._sftp.put(local_path, remote_path)
        os.unlink(local_path)
        print(f"[OK] {remote_path} actualizado")

    # ---- du ----
    def du(self, path="."):
        total = 0
        files = 0
        dirs = 0
        try:
            for item in self._sftp.listdir_attr(path):
                fp = f"{path.rstrip('/')}/{item.filename}"
                if stat_m.S_ISDIR(item.st_mode):
                    try:
                        s, f, d = self.du(fp)
                        total += s
                        files += f
                        dirs += d + 1
                    except Exception:
                        pass
                else:
                    total += item.st_size
                    files += 1
        except PermissionError:
            pass
        return total, files, dirs

    def du_text(self, path="."):
        total, files, dirs = self.du(path)
        return (
            f"{'-' * 40}\n"
            f"  Total: {total:,} bytes ({total/1024/1024:.1f} MB)\n"
            f"  Files: {files:,}\n"
            f"  Dirs:  {dirs:,}"
        )

    # ---- mv / rm / mkdir ----
    def mv(self, src, dst):
        self._sftp.rename(src, dst)
        print(f"[OK] {src} -> {dst}")

    def rm(self, path):
        try:
            a = self._sftp.stat(path)
            if stat_m.S_ISDIR(a.st_mode):
                self._rm_recursive(path)
            else:
                self._sftp.remove(path)
                print(f"[OK] {path} eliminado")
        except FileNotFoundError:
            print(f"[ERR] No existe: {path}")

    def _rm_recursive(self, path):
        for item in self._sftp.listdir_attr(path):
            fp = f"{path}/{item.filename}"
            if stat_m.S_ISDIR(item.st_mode):
                self._rm_recursive(fp)
            else:
                self._sftp.remove(fp)
        self._sftp.rmdir(path)

    def mkdir(self, path):
        self._sftp.mkdir(path)
        print(f"[OK] {path} creado")

    def _progress(self, transferred, total):
        if total == 0:
            return
        pct = transferred * 100 // total
        bar = "#" * (pct // 5) + "." * (20 - pct // 5)
        sys.stdout.write(f"\r  {bar} {pct}% ({transferred:,}/{total:,} bytes)")
        sys.stdout.flush()


def main():
    parser = argparse.ArgumentParser(description="SFTP File Manager para MotoMami")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ls = sub.add_parser("ls", help="Listar directorio remoto")
    p_ls.add_argument("path", nargs="?", default=".", help="Ruta remota")

    p_tree = sub.add_parser("tree", help="Árbol de directorios")
    p_tree.add_argument("path", nargs="?", default=".", help="Ruta remota")
    p_tree.add_argument("--depth", type=int, default=3, help="Máxima profundidad")

    p_get = sub.add_parser("get", help="Descargar archivo/directorio")
    p_get.add_argument("remote", help="Ruta remota")
    p_get.add_argument("local", nargs="?", help="Ruta local")
    p_get.add_argument("-r", "--recursive", action="store_true", help="Recursivo")

    p_put = sub.add_parser("put", help="Subir archivo/directorio")
    p_put.add_argument("local", help="Ruta local")
    p_put.add_argument("remote", nargs="?", help="Ruta remota")
    p_put.add_argument("-r", "--recursive", action="store_true", help="Recursivo")

    p_sync = sub.add_parser("sync", help="Sincronizar directorios")
    p_sync.add_argument("local_dir", help="Directorio local")
    p_sync.add_argument("remote_dir", help="Directorio remoto")
    p_sync.add_argument("direction", nargs="?", default="up",
                        choices=["up", "down"], help="Dirección (default: up)")
    p_sync.add_argument("--dry-run", action="store_true")

    p_find = sub.add_parser("find", help="Buscar archivos por patrón")
    p_find.add_argument("path", default=".", nargs="?", help="Directorio base")
    p_find.add_argument("pattern", help="Patrón glob (ej: *.py)")

    p_info = sub.add_parser("info", help="Información de archivo/directorio")
    p_info.add_argument("path", help="Ruta remota")

    p_cat = sub.add_parser("cat", help="Ver contenido de archivo")
    p_cat.add_argument("path", help="Ruta remota")
    p_cat.add_argument("--max", type=int, default=100000, help="Máx bytes")

    p_edit = sub.add_parser("edit", help="Editar archivo remoto (pull + print)")
    p_edit.add_argument("path", help="Ruta remota")

    p_du = sub.add_parser("du", help="Uso de disco")
    p_du.add_argument("path", nargs="?", default=".", help="Ruta remota")

    p_mv = sub.add_parser("mv", help="Mover/renombrar remoto")
    p_mv.add_argument("src", help="Origen")
    p_mv.add_argument("dst", help="Destino")

    p_rm = sub.add_parser("rm", help="Eliminar archivo/directorio")
    p_rm.add_argument("path", help="Ruta remota")

    p_mkdir = sub.add_parser("mkdir", help="Crear directorio")
    p_mkdir.add_argument("path", help="Ruta remota")

    args = parser.parse_args()

    with SFTPMgr() as mgr:
        if args.cmd == "ls":
            print(mgr.ls_text(args.path))

        elif args.cmd == "tree":
            print(mgr.tree_text(args.path, args.depth))

        elif args.cmd == "get":
            if args.recursive:
                local = args.local or os.path.basename(args.remote.rstrip("/"))
                mgr.get_recursive(args.remote, local)
                print(f"[OK] {args.remote} -> {local}")
            else:
                mgr.get(args.remote, args.local)

        elif args.cmd == "put":
            if args.recursive:
                remote = args.remote or os.path.basename(args.local.rstrip("/"))
                mgr.put_recursive(args.local, remote)
                print(f"[OK] {args.local} -> {remote}")
            else:
                mgr.put(args.local, args.remote)

        elif args.cmd == "sync":
            c, s, e = mgr.sync(args.local_dir, args.remote_dir,
                               args.direction, args.dry_run)
            if args.dry_run:
                print(f"Dry-run: {c} copiarían, {s} saltarían")
            else:
                print(f"[OK] {c} copiados, {s} saltados, {e} errores")

        elif args.cmd == "find":
            results = mgr.find(args.path, args.pattern)
            if results:
                print("\n".join(results))
            else:
                print("(sin resultados)")

        elif args.cmd == "info":
            print(mgr.info(args.path))

        elif args.cmd == "cat":
            print(mgr.cat(args.path, args.max))

        elif args.cmd == "edit":
            local_path, content = mgr.edit_pull(args.path)
            print(f"--- {args.path} ---")
            print(content)
            print(f"--- EOF ({len(content)} chars) ---")
            print(f"\n[INFO] Edita el archivo local y luego ejecuta:")
            print(f"  python tools/sftp_mgr.py put <local_temp> {args.path}")

        elif args.cmd == "du":
            print(mgr.du_text(args.path))

        elif args.cmd == "mv":
            mgr.mv(args.src, args.dst)

        elif args.cmd == "rm":
            mgr.rm(args.path)

        elif args.cmd == "mkdir":
            mgr.mkdir(args.path)

        else:
            parser.print_help()


if __name__ == "__main__":
    main()
