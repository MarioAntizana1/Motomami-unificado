"""
json_ui.py - Renderer de interfaces desde JSON.
Lee un archivo .json con pantallas y componentes y las dibuja vía PIL.
"""
import json
import os
from PIL import Image, ImageDraw
from libs.fb_display import FbDisplay, _find_font


class JsonUI:
    def __init__(self, json_path, fb=None):
        with open(json_path, 'r', encoding='utf-8') as f:
            self._data = json.load(f)
        self._fb = fb or FbDisplay(3)
        self._state = {}           # datos dinámicos que las apps pueden setear
        self._selected = 0         # índice seleccionado en la cuadrícula actual
        self._grid_callbacks = {}  # callbacks por acción de grid

    def screens(self):
        return list(self._data.get("screens", {}).keys())

    def draw(self, screen_name):
        s = self._data.get("screens", {}).get(screen_name)
        if not s:
            return
        self._fb.blank()
        d = self._fb.draw()
        img = self._fb.image()

        bg = s.get("bg", [0, 0, 0])
        d.rectangle([(0, 0), (self._fb.width - 1, self._fb.height - 1)],
                     fill=tuple(bg[:3]))

        for comp in s.get("components", []):
            t = comp.get("type", "")
            x, y = comp.get("x", 0), comp.get("y", 0)

            if t == "rect":
                w, h = comp.get("w", 100), comp.get("h", 30)
                f = comp.get("fill", [40, 40, 60])
                o = comp.get("outline")
                d.rectangle([(x, y), (x + w - 1, y + h - 1)],
                             fill=tuple(f[:3]),
                             outline=tuple(o[:3]) if o else None)

            elif t == "text":
                txt = self._resolve(comp.get("text", ""))
                c = comp.get("color", [255, 255, 255])
                font = _find_font(comp.get("size", 14))
                d.text((x, y), txt, font=font, fill=tuple(c[:3]))

            elif t == "image":
                src = comp.get("src", "")
                w, h = comp.get("w", 100), comp.get("h", 100)
                if src and os.path.exists(src):
                    try:
                        pil_img = Image.open(src).convert("RGB")
                        pil_img = pil_img.resize((w, h))
                        img.paste(pil_img, (x, y))
                    except Exception:
                        d.rectangle([(x, y), (x + w - 1, y + h - 1)],
                                     fill=(20, 20, 40), outline=(60, 60, 80))
                        d.text((x + 4, y + 4), "IMG?", font=_find_font(10), fill=(150, 150, 150))
                else:
                    d.rectangle([(x, y), (x + w - 1, y + h - 1)],
                                 fill=(20, 20, 40), outline=(60, 60, 80))
                    d.text((x + 4, y + 4), "IMG", font=_find_font(10), fill=(150, 150, 150))

            elif t == "label":
                txt = self._resolve(comp.get("text", ""))
                c = comp.get("color", [200, 200, 200])
                w, h = comp.get("w", 0), comp.get("h", 0)
                if w > 0 and h > 0:
                    bgc = comp.get("bg", [0, 0, 0])
                    d.rectangle([(x, y), (x + w - 1, y + h - 1)],
                                 fill=tuple(bgc[:3]))
                font = _find_font(comp.get("size", 12))
                d.text((x, y), txt, font=font, fill=tuple(c[:3]))

            elif t == "grid":
                cols = comp.get("cols", 3)
                cw = comp.get("cell_w", 190)
                ch = comp.get("cell_h", 85)
                gap = comp.get("gap", 8)
                ox = comp.get("offsetX", 0)
                oy = comp.get("offsetY", 0)
                items = comp.get("items", [])

                for i, item in enumerate(items):
                    row, col = divmod(i, cols)
                    gx = x + ox + col * (cw + gap)
                    gy = y + oy + row * (ch + gap)

                    sel = i == self._selected
                    bg_cell = (35, 35, 55) if sel else (15, 15, 28)
                    border = (255, 255, 100) if sel else (40, 40, 55)
                    d.rounded_rectangle(
                        [(gx, gy), (gx + cw - 1, gy + ch - 1)],
                        radius=6, fill=bg_cell, outline=border,
                        width=2 if sel else 1
                    )

                    # círculo icono
                    icon_color = item.get("color", [100, 200, 255])
                    if sel:
                        pass
                    else:
                        icon_color = [max(0, v - 100) for v in icon_color]
                    cx, cy = gx + cw // 2, gy + 30
                    r = 16
                    d.ellipse([(cx - r, cy - r), (cx + r, cy + r)],
                               fill=tuple(icon_color[:3]))

                    icon_text = item.get("icon", "X")[:3]
                    font_icon = _find_font(13)
                    bb = d.textbbox((0, 0), icon_text, font=font_icon)
                    tw = bb[2] - bb[0]
                    th = bb[3] - bb[1]
                    d.text((cx - tw // 2, cy - th // 2 - 1), icon_text,
                            font=font_icon, fill=(255, 255, 255))

                    # nombre
                    name = item.get("label", "")
                    font_name = _find_font(11)
                    bb2 = d.textbbox((0, 0), name, font=font_name)
                    nw = bb2[2] - bb2[0]
                    name_c = (255, 255, 255) if sel else (160, 160, 180)
                    d.text((gx + (cw - nw) // 2, gy + 60), name,
                            font=font_name, fill=name_c)

        self._fb.update()

    def _resolve(self, text):
        if text.startswith("$") and text[1:] in self._state:
            return str(self._state[text[1:]])
        return text

    def set_state(self, **kwargs):
        self._state.update(kwargs)

    def navigate(self, direction):
        s = self._data.get("screens", {}).get(self._current_screen, {})
        for comp in s.get("components", []):
            if comp.get("type") == "grid":
                cols = comp.get("cols", 3)
                items = comp.get("items", [])
                if direction == "UP":
                    self._selected = max(0, self._selected - cols)
                elif direction == "DOWN":
                    self._selected = min(len(items) - 1, self._selected + cols)
                elif direction == "LEFT":
                    self._selected = max(0, self._selected - 1)
                elif direction == "RIGHT":
                    self._selected = min(len(items) - 1, self._selected + 1)
                return

    def get_action(self):
        s = self._data.get("screens", {}).get(self._current_screen, {})
        for comp in s.get("components", []):
            if comp.get("type") == "grid":
                items = comp.get("items", [])
                if 0 <= self._selected < len(items):
                    return items[self._selected].get("action", "")
        return ""

    def show(self, screen_name, state=None):
        self._current_screen = screen_name
        self._selected = 0
        if state:
            self._state.update(state)
        self.draw(screen_name)
