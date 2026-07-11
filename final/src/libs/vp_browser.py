"""vp_browser.py - Navegador de archivos de video"""
import os
from vp_config import BASE_DIR, VIDEO_EXT, SEARCH_FOLDERS


class FileBrowser:
    """Navega y selecciona archivos de video en el sistema de archivos."""

    def __init__(self):
        self.files = []       # Rutas completas
        self.names = []       # Solo nombres de archivo
        self.selected = 0     # Indice seleccionado
        self.playing_idx = -1 # Indice del que se reproduce
        self.scroll = 0       # Desplazamiento en la lista
        self.current_folder = BASE_DIR

        # Por defecto, empezar en movies/
        for f in ['movies', 'Movies', 'videos']:
            p = os.path.join(BASE_DIR, f)
            if os.path.isdir(p):
                self.current_folder = p
                break

        self.refresh()

    def refresh(self):
        """Busca archivos de video en todas las carpetas configuradas."""
        self.files = []
        self.names = []
        buscadas = set()

        # Primero la carpeta actual
        if os.path.isdir(self.current_folder):
            for root, dirs, fs in os.walk(self.current_folder):
                for f in fs:
                    if f.lower().endswith(VIDEO_EXT):
                        self.files.append(os.path.join(root, f))
                        self.names.append(f)

        # Si no encuentra, buscar en SEARCH_FOLDERS
        if not self.files:
            for folder in SEARCH_FOLDERS:
                if os.path.isdir(folder) and folder not in buscadas:
                    buscadas.add(folder)
                    for root, dirs, fs in os.walk(folder):
                        for f in fs:
                            if f.lower().endswith(VIDEO_EXT):
                                self.files.append(os.path.join(root, f))
                                self.names.append(f)

        # Ordenar alfabeticamente
        if self.files:
            pares = sorted(zip(self.names, self.files), key=lambda x: x[0].lower())
            self.names = [p[0] for p in pares]
            self.files = [p[1] for p in pares]

        print(f"[Browser] {len(self.files)} videos encontrados")
        self.selected = 0
        self.scroll = 0

    def get_display_list(self):
        """Devuelve una lista formateada para mostrar.

        Returns:
            [(idx, nombre, is_playing), ...]
        """
        res = []
        for i in range(self.scroll, min(self.scroll + 20, len(self.files))):
            if i < len(self.files):
                res.append((i, self.names[i], i == self.playing_idx))
        return res

    def move_up(self):
        """Mueve la seleccion hacia arriba."""
        if self.selected > 0:
            self.selected -= 1
            if self.selected < self.scroll:
                self.scroll = self.selected

    def move_down(self):
        """Mueve la seleccion hacia abajo."""
        if self.selected < len(self.files) - 1:
            self.selected += 1
            if self.selected >= self.scroll + 8:
                self.scroll = self.selected - 7

    def get_selected_path(self):
        """Devuelve la ruta completa del archivo seleccionado."""
        if 0 <= self.selected < len(self.files):
            return self.files[self.selected]
        return None

    def set_playing(self, idx):
        """Marca el indice del archivo que se esta reproduciendo."""
        self.playing_idx = idx
