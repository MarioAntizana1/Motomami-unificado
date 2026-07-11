"""fb_display.py - Framebuffer nativo + compatibilidad con apps viejas"""
import mmap, os
from PIL import Image, ImageDraw, ImageFont
try:
    import numpy as np; _HAS_NUMPY = True
except: _HAS_NUMPY = False

def _sysfs(fb, attr):
    with open(f"/sys/class/graphics/{fb}/{attr}") as f: return f.read().strip()

class FramebufferDisplay:
    def __init__(self, fb_path="/dev/fb1"):
        self.fb_path = fb_path
        fn = os.path.basename(fb_path)
        w, h = _sysfs(fn, "virtual_size").split(",")
        self.width = int(w); self.height = int(h)
        self.bits_per_pixel = int(_sysfs(fn, "bits_per_pixel"))
        self.bytes_per_pixel = self.bits_per_pixel // 8
        self.buf_size = self.width * self.height * self.bytes_per_pixel
        self._fd = os.open(self.fb_path, os.O_RDWR)
        self._mmap = mmap.mmap(self._fd, self.buf_size, mmap.MAP_SHARED, mmap.PROT_READ|mmap.PROT_WRITE)
    def _to_rgb565(self, img):
        if img.size != (self.width, self.height): img = img.resize((self.width, self.height))
        if img.mode != "RGB": img = img.convert("RGB")
        if _HAS_NUMPY:
            a = np.asarray(img, dtype=np.uint16)
            return ((a[:,:,0]>>3)<<11 | (a[:,:,1]>>2)<<5 | (a[:,:,2]>>3)).astype("<u2").tobytes()
        out = bytearray(self.buf_size); px = img.load(); i = 0
        for y in range(self.height):
            for x in range(self.width):
                r,g,b = px[x,y]; v = ((r>>3)<<11)|((g>>2)<<5)|(b>>3)
                out[i]=v&0xFF; out[i+1]=(v>>8)&0xFF; i+=2
        return bytes(out)
    def show(self, img):
        d = self._to_rgb565(img); self._mmap.seek(0); self._mmap.write(d)
    def close(self): self._mmap.close(); os.close(self._fd)

# Retrocompatibilidad con apps viejas (no tocan SPI, usan los fb reales)
W, H = 320, 240
_d1 = FramebufferDisplay("/dev/fb1")
_d2 = FramebufferDisplay("/dev/fb2")
daemon_available = lambda: True

class FbDisplay:
    def __init__(self, disp_id=1):
        self.id = disp_id
        self.width = 640 if disp_id == 3 else W
        self.height = H
        from PIL import Image, ImageDraw, ImageFont
        self._img = Image.new("RGB", (self.width, self.height), (0,0,0))
        self._draw = ImageDraw.Draw(self._img)
        try:
            self.font_title = ImageFont.truetype("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 18)
            self.font = ImageFont.truetype("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 14)
            self.font_s = ImageFont.truetype("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 11)
            self.font_big = ImageFont.truetype("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 40)
        except:
            self.font_title = self.font = self.font_s = self.font_big = ImageFont.load_default()
    def blank(self): self._img = Image.new("RGB", (self.width, self.height), (0,0,0)); self._draw = ImageDraw.Draw(self._img)
    def draw(self): return self._draw
    def image(self): return self._img
    def update(self):
        if self.id == 3:
            _d1.show(self._img.crop((0,0,W,H)))
            _d2.show(self._img.crop((W,0,W*2,H)))
        elif self.id == 1: _d1.show(self._img)
        else: _d2.show(self._img)
    def close(self): self.blank(); self.update()
