#!/usr/bin/env python3
"""music_player.py - NATIVE FRAMEBUFFER edition"""
import os, sys, time, glob, select, termios, tty

if os.geteuid() == 0:
    os.environ.setdefault('PULSE_RUNTIME_PATH', '/run/user/1000/pulse')
    os.environ.setdefault('XDG_RUNTIME_DIR', '/run/user/1000')
os.environ.setdefault('SDL_AUDIODRIVER', 'alsa')
os.environ.setdefault('AUDIODEV', 'hw:1,0')
os.environ['ALSA_BUFFER_SIZE'] = '32768'
os.environ['ALSA_PERIOD_SIZE'] = '4096'

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_BASE_DIR = os.path.dirname(_THIS_DIR)
sys.path.insert(0, os.path.join(_BASE_DIR, 'lib'))

from fb_display import FbDisplay
import board, digitalio
from PIL import Image, ImageDraw, ImageFont
try: from vp_controller import XboxController
except: XboxController = None

AUDIO_EXT = ('.mp3', '.wav', '.flac', '.ogg')
MUSIC_DIR = "/home/motomami/final/music"
INITIAL_VOLUME = 70; VOLUME_STEP = 5

KEY_MAP = {'k':'UP','j':'DOWN','h':'LEFT','l':'RIGHT',' ':'ENTER','\x1b':'BACK','a':'X','s':'Y','z':'L3','c':'R3','q':'QUIT'}

def _init_kb():
    try: fd=sys.stdin.fileno(); old=termios.tcgetattr(fd); tty.setraw(fd); return old
    except: return None
def _restore_kb(old):
    if not old: return
    try: termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old)
    except: pass
def _read_key():
    try:
        if select.select([sys.stdin],[],[],0.0)[0]:
            ch=sys.stdin.read(1)
            if ch and 'A'<=ch<='Z': ch=ch.lower()
            return ch
    except: pass
    return None

class AudioPlayer:
    def __init__(self):
        self.music_file=None; self.volume=INITIAL_VOLUME; self.is_playing=False; self.is_paused=False
        self.duration=0.0; self.position=0.0; self._ok=False
    def _free_dac(self):
        import subprocess as sp
        d='/dev/snd/pcmC1D0p'
        if not os.path.exists(d): return
        for att in range(4):
            for p in ['wireplumber','pipewire-pulse']:
                try: sp.run(['pkill','-9',p],capture_output=True,timeout=2)
                except: pass
            try:
                out=sp.run(['fuser',d],capture_output=True,text=True,timeout=2).stdout.strip()
                if not out:
                    if att>0: print(f"[Audio] DAC freed (att {att+1})")
                    return
                for tok in out.split():
                    try: os.kill(int(tok),9)
                    except: pass
                time.sleep(0.3)
            except: pass
    def init_pygame(self):
        self._free_dac()
        try:
            import pygame  # no pygame.init()
            pygame.mixer.pre_init(frequency=22050,size=-16,channels=2,buffer=8192,allowedchanges=0)
            self._free_dac()
            pygame.mixer.init()
            self._ok=True; pygame.mixer.music.set_volume(self.volume/100.0)
            print(f"[Audio] listo. Vol={self.volume}%")
        except Exception as e: print(f"[Audio] Error: {e}")
    def load(self,fp):
        if not self._ok: return False
        try:
            import pygame; pygame.mixer.music.load(fp)
            self.music_file=fp; self.duration=self._dur(fp); self.position=0.0
            self.is_playing=False; self.is_paused=False; return True
        except Exception as e: print(f"[Audio] Error load: {e}"); return False
    def _dur(self,fp):
        try:
            import mutagen; i=mutagen.File(fp)
            if i and i.info: return i.info.length
        except: pass
        return 0.0
    def play(self):
        if not self._ok or not self.music_file: return
        try:
            import pygame
            if self.is_paused: pygame.mixer.music.unpause(); self.is_paused=False
            else: pygame.mixer.music.play()
            self.is_playing=True
        except: pass
    def pause(self):
        if not self.is_playing or not self._ok: return
        try:
            import pygame
            if self.is_paused: pygame.mixer.music.unpause(); self.is_paused=False
            else: pygame.mixer.music.pause(); self.is_paused=True
        except: pass
    def stop(self):
        if not self._ok: return
        try:
            import pygame; pygame.mixer.music.stop()
            self.is_playing=False; self.is_paused=False; self.position=0.0
        except: pass
    def seek(self,s):
        if not self.is_playing or not self._ok: return
        try:
            import pygame; c=self.get_pos(); n=max(0,min(c+s,self.duration))
            pygame.mixer.music.rewind(); pygame.mixer.music.set_pos(n)
        except: pass
    def set_volume(self,v):
        self.volume=max(0,min(100,v))
        if self._ok:
            try:
                import pygame; pygame.mixer.music.set_volume(self.volume/100.0)
            except: pass
    def get_pos(self):
        if not self._ok or not self.is_playing: return self.position
        try:
            import pygame; ms=pygame.mixer.music.get_pos()
            if ms>=0: self.position=ms/1000.0
        except: pass
        return self.position
    def is_music_finished(self):
        if not self._ok: return True
        try:
            import pygame
            if self.is_playing and not self.is_paused and not pygame.mixer.music.get_busy(): return True
        except: pass
        return False
    def _fmt_time(self,s): return f"{int(s//60):02d}:{int(s%60):02d}"
    def quit(self):
        try:
            import pygame; pygame.mixer.music.stop(); pygame.mixer.quit()
        except: pass
        self._ok=False

class MusicBrowser:
    def __init__(self):
        self.files=[]; self.names=[]; self.is_dir=[]; self.selected=0; self.playing_idx=-1; self.scroll=0
        self.current_folder=MUSIC_DIR; self.root_folder=MUSIC_DIR; self._hist=[]
        self.refresh()
    def refresh(self):
        self.files=[]; self.names=[]; self.is_dir=[]
        if not os.path.isdir(self.current_folder): return
        dirs=[]; files=[]
        try: entries=sorted(os.listdir(self.current_folder),key=str.lower)
        except: entries=[]
        for e in entries:
            full=os.path.join(self.current_folder,e)
            if os.path.isdir(full): dirs.append((full,e))
            elif e.lower().endswith(AUDIO_EXT): files.append((full,e))
        for p,n in dirs: self.files.append(p); self.names.append(f"[DIR] {n}"); self.is_dir.append(True)
        for p,n in files: self.files.append(p); self.names.append(n); self.is_dir.append(False)
        self.selected=0; self.scroll=0
    def clean_name(self,n):
        if n.startswith("[DIR] "): return n
        return os.path.splitext(n)[0].replace('_',' ').replace('-',' ').strip()
    def get_display_list(self):
        r=[]
        for i in range(self.scroll,min(self.scroll+8,len(self.files))):
            r.append((i,self.clean_name(self.names[i]),i==self.playing_idx))
        return r
    def move_up(self):
        if self.selected>0: self.selected-=1
        if self.selected<self.scroll: self.scroll=self.selected
    def move_down(self):
        if self.selected<len(self.files)-1: self.selected+=1
        if self.selected>=self.scroll+8: self.scroll=self.selected-7
    def get_selected_path(self):
        if 0<=self.selected<len(self.files): return self.files[self.selected]
        return None
    def get_selected_is_dir(self):
        if 0<=self.selected<len(self.is_dir): return self.is_dir[self.selected]
        return False
    def set_playing(self,i): self.playing_idx=i
    def navigate_into(self):
        if not self.get_selected_is_dir(): return False
        p=self.get_selected_path()
        if not p or not os.path.isdir(p): return False
        self._hist.append(self.current_folder); self.current_folder=p; self.playing_idx=-1; self.refresh(); return True
    def navigate_up(self):
        if not self._hist: return False
        self.current_folder=self._hist.pop(); self.playing_idx=-1; self.refresh(); return True
    def current_path_display(self):
        p=self.current_folder
        if p.startswith(self.root_folder): rel=p[len(self.root_folder):]; return f"~{rel}" if rel else "~/music"
        return p

class MusicApp:
    def __init__(self):
        print("="*45); print("  MUSIC PLAYER (Native FB)"); print("="*45)
        self.player=AudioPlayer(); self.browser=MusicBrowser(); self.fb=FbDisplay(3)
        BTNS={'UP':board.D13,'DOWN':board.D26,'LEFT':board.D6,'RIGHT':board.D5,'ENTER':board.D12,'BACK':board.D16}
        self.btns={}; self.bprev={}
        for n,p in BTNS.items():
            try:
                for _ in range(5):
                    try: btn=digitalio.DigitalInOut(p); break
                    except: time.sleep(0.1)
                else: btn=None
                if btn: btn.direction=digitalio.Direction.INPUT; btn.pull=digitalio.Pull.DOWN; self.btns[n]=btn; self.bprev[n]=False
            except Exception as e: print(f"[Btn {n}] {e}")
        self.ctrl=XboxController() if XboxController else None
        self.running=False; self.mode='browser'; self.last_upd=0
        self._kb=_init_kb(); self._xbox=False

    def draw(self):
        self.fb.blank(); d=self.fb.draw(); D=(80,80,80)
        d.rectangle([(0,0),(640,240)],fill=(0,0,8))
        d.line([(319,0),(319,239)],fill=D,width=2)
        # Left: Now Playing
        d.rectangle([(0,0),(318,27)],fill=(80,20,120))
        d.text((8,4),"MUSICA",font=self.fb.font_title,fill=(255,255,255))
        y=36
        if self.player.music_file:
            t=self.browser.clean_name(os.path.basename(self.player.music_file))[:40]
        else: t="---"
        d.text((8,y),t,font=self.fb.font_title,fill=(200,180,255)); y+=26
        total=sum(1 for x in self.browser.is_dir if not x)
        d.text((8,y),f"{total} canciones",font=self.fb.font_s,fill=(130,130,160))
        y=78; dur=self.player.duration; pos=self.player.get_pos(); pct=int(pos/dur*100) if dur>0 else 0
        bw=302
        d.rectangle([(8,y),(8+bw,y+12)],fill=(20,20,40),outline=(60,60,80))
        if pct>0: d.rectangle([(8,y),(8+int(bw*pct/100),y+12)],fill=(200,100,255))
        d.text((8,y+14),self.player._fmt_time(pos),font=self.fb.font_s,fill=(180,180,200))
        d.text((260,y+14),self.player._fmt_time(dur),font=self.fb.font_s,fill=(180,180,200))
        d.text((140,y+14),f"{pct}%",font=self.fb.font_s,fill=(200,180,255))
        y=112
        if self.player.is_playing:
            st,sc=("PAUSADO",(255,200,50)) if self.player.is_paused else ("PLAY",(100,255,100))
        else: st,sc=("DETENIDO",(200,100,100))
        d.text((100,y),st,font=self.fb.font,fill=sc)
        d.text((8,y+28),f"Vol: {self.player.volume}%",font=self.fb.font_s,fill=(180,180,200))
        for i,h in enumerate(["ENTER:Play/Pause  BACK:Stop","Arriba/Abajo: Vol/Nav"]):
            d.text((8,195+i*14),h,font=self.fb.font_s,fill=(100,100,130))
        # Right: Playlist
        ox=321; p=self.browser.current_path_display()
        d.rectangle([(ox,0),(ox+318,23)],fill=(30,15,50))
        d.text((ox+8,3),p[:28],font=self.fb.font_s,fill=(200,150,255))
        d.line([(ox,23),(ox+318,23)],fill=(60,30,80))
        vis=self.browser.get_display_list()[:8]; yy=28
        for i,nm,pl in vis:
            isd=i<len(self.browser.is_dir) and self.browser.is_dir[i]
            pf="  "; fg=(100,130,200) if isd else (140,140,160)
            if i==self.browser.selected:
                d.rectangle([(ox+2,yy-1),(ox+316,yy+22)],fill=(40,20,60),outline=(200,100,255))
                pf="> "; fg=(255,255,255)
            if pl: fg=(100,255,100); pf="> "
            d.text((ox+8,yy+3),f"{pf}{nm[:24]}",font=self.fb.font_s,fill=fg); yy+=24
        if not vis: d.text((ox+10,50),"Carpeta vacia",font=self.fb.font,fill=(200,100,0))
        if self.player.is_playing and self.player.music_file:
            n2=self.browser.clean_name(os.path.basename(self.player.music_file))[:18]
            d.text((ox+4,225),f"Now: {n2}",font=self.fb.font_s,fill=(100,200,100))
        self.fb.update()

    def _splash(self):
        self.fb.blank(); d=self.fb.draw()
        d.text((200,100),"Music Player",font=self.fb.font_big,fill=(200,100,255)); self.fb.update()

    def _play_sel(self):
        p=self.browser.get_selected_path()
        if p and os.path.exists(p) and not self.browser.get_selected_is_dir():
            self.player.stop(); time.sleep(0.05)
            if self.player.load(p): self.player.play(); self.browser.set_playing(self.browser.selected); self.mode='playing'

    def _play_next(self):
        ai=[i for i,d in enumerate(self.browser.is_dir) if not d]
        if not ai: return
        try: n=ai[(ai.index(self.browser.playing_idx)+1)%len(ai)]
        except ValueError: n=ai[0]
        self.browser.selected=n; self._play_sel()

    def _act(self,a):
        if a=='UP':
            if self.mode=='playing' and self.player.is_playing: self.player.set_volume(self.player.volume+VOLUME_STEP)
            else: self.browser.move_up()
        elif a=='DOWN':
            if self.mode=='playing' and self.player.is_playing: self.player.set_volume(self.player.volume-VOLUME_STEP)
            else: self.browser.move_down()
        elif a=='LEFT':
            if self.mode=='playing': self.player.seek(-10)
        elif a=='RIGHT':
            if self.mode=='playing': self.player.seek(10)
        elif a=='ENTER':
            if self.mode=='browser':
                if self.browser.get_selected_is_dir(): self.browser.navigate_into()
                else: self._play_sel()
            else:
                if not self.player.is_playing and not self.player.is_paused:
                    if self.player.music_file: self.player.play()
                    else: self._play_sel()
                else: self.player.pause()
        elif a=='BACK':
            if self.mode=='playing': self.player.stop(); self.mode='browser'
            else:
                if self.browser.navigate_up(): pass
                else: self.running=False
        elif a=='X': self.player.set_volume(self.player.volume-VOLUME_STEP)
        elif a=='Y': self.player.set_volume(self.player.volume+VOLUME_STEP)
        elif a=='QUIT': self.running=False
        self.draw()

    def run(self):
        self._splash(); self.player.init_pygame()
        if self.ctrl and self.ctrl.connect(): self.ctrl.start(); self._xbox=True
        self.browser.refresh(); self.draw(); self.running=True
        while self.running:
            n=time.time()
            for nm,b in list(self.btns.items()):
                try: cur=b.value
                except: cur=False
                if cur and not self.bprev.get(nm,False): self.bprev[nm]=True; self._act(nm)
                self.bprev[nm]=cur
            if self._xbox:
                evt=self.ctrl.get_event(0.005)
                while evt:
                    if evt[0]=='btn':
                        b=evt[1]
                        if b in (self.ctrl.DPAD_U,300): self._act('UP')
                        elif b in (self.ctrl.DPAD_D,301): self._act('DOWN')
                        elif b in (self.ctrl.DPAD_L,302): self._act('LEFT')
                        elif b in (self.ctrl.DPAD_R,303): self._act('RIGHT')
                        elif b==self.ctrl.A: self._act('ENTER')
                        elif b==self.ctrl.B: self._act('BACK')
                        elif b==self.ctrl.X: self._act('X')
                        elif b==self.ctrl.Y: self._act('Y')
                    evt=self.ctrl.get_event(0.005)
            else:
                ch=_read_key()
                if ch and ch in KEY_MAP: self._act(KEY_MAP[ch])
            if self.mode=='playing' and self.player.is_music_finished():
                self._play_next()
            if self.mode=='playing' and n-self.last_upd>1.0: self.last_upd=n; self.draw()
            time.sleep(0.03)
        self.player.quit()
        for b in self.btns.values():
            try: b.deinit()
            except: pass
        _restore_kb(self._kb)
        if self.ctrl: self.ctrl.stop()
        self.fb.close()

if __name__=='__main__':
    app=MusicApp()
    try: app.run()
    except KeyboardInterrupt: print("\nInterrumpido"); app.player.quit(); _restore_kb(app._kb); app.fb.close()
    except Exception as e: print(f"\nError: {e}"); import traceback; traceback.print_exc(); app.player.quit(); _restore_kb(app._kb); app.fb.close()
