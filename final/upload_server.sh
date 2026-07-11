#!/bin/bash
# upload_server.sh - Servidor HTTP de subida de archivos para MotoMami Pi
# ========================================================================
# Uso:  ./upload_server.sh [puerto]
# Por defecto escucha en el puerto 8080
#
# Subir archivos desde Windows:
#   Abrir http://192.168.31.195:8080/ en el navegador
#   Usar el formulario "Elegir archivo" y "Subir"
#
# O desde PowerShell:
#   $file = "C:\ruta\cancion.mp3"
#   Invoke-WebRequest -Uri http://192.168.31.195:8080/upload `
#     -Method Post -Form @{file=(Get-Item $file)} -OutVariable r
#
# ========================================================================

PORT=${1:-8080}
MUSIC_DIR="/home/motomami/final/music"

# Asegurar que el directorio de musica existe
mkdir -p "$MUSIC_DIR"

echo "============================================================"
echo "  MotoMami Upload Server"
echo "  Puerto: $PORT"
echo "  Destino: $MUSIC_DIR"
echo "============================================================"
echo ""
echo "  Abre http://$(hostname -I | awk '{print $1}'):$PORT/"
echo "  (o http://192.168.31.195:$PORT/ si no detecta IP)"
echo ""

# Crear script Python temporal para el servidor
python3 -c "
import http.server
import cgi
import os
import shutil
import urllib.parse

PORT = $PORT
MUSIC_DIR = '$MUSIC_DIR'

class UploadHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == '/':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            html = '''<!DOCTYPE html>
<html><head><meta charset=\"utf-8\">
<title>MotoMami Upload</title>
<style>
body { font-family: Arial, sans-serif; background: #1a1a2e; color: #eee; margin: 0; padding: 20px; text-align: center; }
h1 { color: #c864ff; }
.container { max-width: 600px; margin: 0 auto; padding: 30px; background: #16213e; border-radius: 10px; border: 1px solid #c864ff; }
form { margin: 20px 0; }
input[type=file] { background: #0f3460; color: #eee; padding: 10px; border: 1px solid #c864ff; border-radius: 5px; width: 80%; }
input[type=submit] { background: #c864ff; color: #000; padding: 10px 30px; border: none; border-radius: 5px; font-size: 16px; cursor: pointer; margin-top: 10px; }
input[type=submit]:hover { background: #e080ff; }
.files { margin-top: 20px; text-align: left; }
.files ul { list-style: none; padding: 0; }
.files li { padding: 4px 0; color: #aaa; font-size: 13px; }
.files li:before { content: \"♪ \"; color: #c864ff; }
.msg { padding: 10px; margin: 10px 0; border-radius: 5px; }
.success { background: #1b4332; color: #95d5b2; border: 1px solid #52b788; }
.error { background: #4a0e0e; color: #ff9999; border: 1px solid #cc3333; }
</style></head><body>
<div class=\"container\">
<h1>♪ MotoMami Upload</h1>
<p>Sube musica a la Raspberry Pi</p>
<form action=\"/upload\" method=\"post\" enctype=\"multipart/form-data\">
<input type=\"file\" name=\"file\" multiple required><br>
<input type=\"submit\" value=\"Subir archivo(s)\">
</form>
<div class=\"files\">
<h3>Archivos en el reproductor:</h3>
<ul>'''
            # List files in music directory
            if os.path.isdir(MUSIC_DIR):
                files = sorted([f for f in os.listdir(MUSIC_DIR) if os.path.isfile(os.path.join(MUSIC_DIR, f))])
                for f in files:
                    size = os.path.getsize(os.path.join(MUSIC_DIR, f))
                    if size > 1024*1024:
                        s = f'{size/1024/1024:.1f} MB'
                    elif size > 1024:
                        s = f'{size/1024:.1f} KB'
                    else:
                        s = f'{size} B'
                    html += f'<li>{f} ({s})</li>'
            if 'files' not in dir() or not files:
                html += '<li style=\"color:#555\">(vacio - sube musica!)</li>'
            html += '''</ul></div></div></body></html>'''
            self.wfile.write(html.encode('utf-8'))

        elif path == '/list':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            if os.path.isdir(MUSIC_DIR):
                files = sorted(os.listdir(MUSIC_DIR))
            else:
                files = []
            import json
            self.wfile.write(json.dumps({'files': files}).encode('utf-8'))

        else:
            super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == '/upload':
            form = cgi.FieldStorage(fp=self.rfile, headers=self.headers,
                                    environ={'REQUEST_METHOD': 'POST'})
            uploaded = []
            errors = []
            
            if 'file' in form:
                items = form['file']
                if not isinstance(items, list):
                    items = [items]
                for item in items:
                    if item.filename:
                        safe_name = os.path.basename(item.filename)
                        dest = os.path.join(MUSIC_DIR, safe_name)
                        try:
                            with open(dest, 'wb') as f:
                                shutil.copyfileobj(item.file, f)
                            uploaded.append(safe_name)
                            print(f'[Upload] Recibido: {safe_name}')
                        except Exception as e:
                            errors.append(f'{safe_name}: {e}')
                            print(f'[Upload] Error {safe_name}: {e}')

            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            msg = '<html><head><meta charset=\"utf-8\"><title>Subido</title>'
            msg += '<meta http-equiv=\"refresh\" content=\"2;url=/\">'
            msg += '<style>body{font-family:Arial;background:#1a1a2e;color:#eee;padding:40px;text-align:center}</style></head><body>'
            if uploaded:
                msg += f'<h2>✅ Subido: {len(uploaded)} archivo(s)</h2><ul>'
                for f in uploaded:
                    msg += f'<li>♪ {f}</li>'
                msg += '</ul>'
            if errors:
                msg += f'<h3 style=\"color:#cc3333\">❌ Errores:</h3><ul>'
                for e in errors:
                    msg += f'<li>{e}</li>'
                msg += '</ul>'
            msg += '<p><a href=\"/\" style=\"color:#c864ff\">Volver</a></p></body></html>'
            self.wfile.write(msg.encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

# Ensure music dir exists
os.makedirs(MUSIC_DIR, exist_ok=True)

server = http.server.HTTPServer(('0.0.0.0', PORT), UploadHandler)
print(f'[Upload Server] Escuchando en 0.0.0.0:{PORT}')
print(f'[Upload Server] Directorio: {MUSIC_DIR}')
print(f'[Upload Server] Archivos actuales: {len(os.listdir(MUSIC_DIR)) if os.path.isdir(MUSIC_DIR) else 0}')
try:
    server.serve_forever()
except KeyboardInterrupt:
    print('\n[Upload Server] Detenido.')
    server.server_close()
"
