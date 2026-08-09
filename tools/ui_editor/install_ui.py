#!/usr/bin/env python3
"""
install_ui.py - Instala un archivo JSON de UI y extrae sus imágenes.
Uso: python3 install_ui.py motomami_ui.json [--dir /home/motomami/moto]
"""
import sys, os, json, base64

DEST = "/home/motomami/moto"


def install(json_path, dest=DEST):
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    images = data.pop("_images", {})
    json_dest = os.path.join(dest, "motomami_ui.json")

    # Guardar JSON limpio (sin _images)
    with open(json_dest, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"JSON guardado: {json_dest}")

    # Extraer imágenes
    if images:
        img_dir = os.path.join(dest, "img")
        os.makedirs(img_dir, exist_ok=True)
        for path, b64 in images.items():
            full = os.path.join(dest, path)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, 'wb') as f:
                f.write(base64.b64decode(b64))
            print(f"  Imagen: {full}")
    print("Instalación completa.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    install(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else DEST)
