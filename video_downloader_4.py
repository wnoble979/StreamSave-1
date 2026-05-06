#!/usr/bin/env python3
"""
StreamSave v4  ·  Universal Video Downloader
Beautiful GUI  ·  Paste-only URL box  ·  Dropdown-only format selection
Queue system  ·  Auto & Manual mode  ·  yt-dlp powered
"""

# ── Auto-install ──────────────────────────────────────────────────────────────
import sys, subprocess
for _pkg, _imp in [("customtkinter","customtkinter"),("pillow","PIL"),("yt-dlp","yt_dlp")]:
    try: __import__(_imp)
    except ImportError:
        subprocess.check_call([sys.executable,"-m","pip","install",_pkg,"-q"]
                              +([" --break-system-packages"] if sys.platform!="win32" else []))

# ── Imports ───────────────────────────────────────────────────────────────────
import os, re, shutil, glob, atexit, threading, queue, time, io
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageDraw
import yt_dlp

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# ══════════════════════════════════════════════════════════════════════════════
#  AURORA DARK PALETTE
# ══════════════════════════════════════════════════════════════════════════════
# Backgrounds  (layered depth)
B0 = "#080b14"    # root — deepest space
B1 = "#0c1020"    # sidebar / right panel
B2 = "#0f1428"    # main area
B3 = "#131830"    # cards
B4 = "#1a2040"    # input fields / hover
B5 = "#212850"    # elevated cards

# Borders
BD  = "#252d50"   # dim border
BDA = "#4a5a9a"   # active border

# Semantic accents
VIOLET  = "#8b5cf6"   # primary
INDIGO  = "#6366f1"   # secondary
BLUE    = "#3b82f6"   # info
CYAN    = "#06b6d4"   # live / active
TEAL    = "#14b8a6"   # success
AMBER   = "#f59e0b"   # warning / fetching
RED     = "#ef4444"   # error
PINK    = "#ec4899"   # highlight
LIME    = "#84cc16"   # done

# Glow helper (used in progress bar gradient)
GLOW_V  = (139, 92, 246)   # violet rgb
GLOW_C  = (6,  182, 212)   # cyan rgb

# Text
TX1 = "#f1f5f9"   # primary
TX2 = "#94a3b8"   # secondary
TX3 = "#475569"   # muted
TX4 = "#1e293b"   # on-bright backgrounds

# Status map
SCOL = {
    "PENDING"    : TX3,
    "FETCHING"   : AMBER,
    "READY"      : BLUE,
    "DOWNLOADING": CYAN,
    "DONE"       : LIME,
    "ERROR"      : RED,
    "CANCELLED"  : TX3,
}

# ── Options ───────────────────────────────────────────────────────────────────
APP   = "StreamSave"
VER   = "4.0"
WW,WH = 1200, 800
SBW   = 288       # sidebar width
RPW   = 328       # right panel width
TW,TH = 152, 86   # thumbnail 16:9

RESOLUTIONS = ["Best Available","4K — 2160p","1080p HD","720p HD",
               "480p SD","360p SD","Audio Only"]
CONTAINERS  = ["MP4  (h264 + aac — recommended)","MKV  (any codec)","WEBM  (vp9 + opus)"]
AUDIO_EXTS  = ["MP3","M4A (AAC)","OPUS","FLAC","WAV"]

# ── ffmpeg ────────────────────────────────────────────────────────────────────
def _find_ffmpeg() -> Optional[str]:
    p = shutil.which("ffmpeg")
    if p: return p
    for c in [r"C:\ffmpeg\bin\ffmpeg.exe",
              r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
              os.path.join(os.environ.get("LOCALAPPDATA",""),"Programs","ffmpeg","bin","ffmpeg.exe"),
              os.path.join(os.environ.get("USERPROFILE",""),"ffmpeg","bin","ffmpeg.exe"),
              os.path.join(os.path.dirname(os.path.abspath(__file__)),"ffmpeg.exe")]:
        if c and os.path.isfile(c): return c
    return None
FFMPEG = _find_ffmpeg()

# ── cleanup ───────────────────────────────────────────────────────────────────
_PARTS: List[str] = []
def _cleanup():
    for p in _PARTS:
        for f in glob.glob(p):
            try: os.remove(f)
            except OSError: pass
atexit.register(_cleanup)

# ══════════════════════════════════════════════════════════════════════════════
#  DATA MODEL
# ══════════════════════════════════════════════════════════════════════════════
@dataclass
class Item:
    url:      str
    iid:      str   = field(default_factory=lambda: str(time.time_ns()))
    title:    str   = "Fetching info…"
    dur:      int   = 0
    thumb_url:str   = ""
    status:   str   = "PENDING"
    error:    str   = ""
    fmt_str:  str   = ""
    pct:      float = 0.0
    speed:    float = 0.0
    eta:      int   = 0
    dl:       int   = 0
    total:    int   = 0
    vopts:    List  = field(default_factory=list)   # (label, fid, height)
    aopts:    List  = field(default_factory=list)   # (label, fid, abr)
    info:     Any   = None
    thumb_img:Any   = None   # CTkImage

# ══════════════════════════════════════════════════════════════════════════════
#  FORMAT LOGIC
# ══════════════════════════════════════════════════════════════════════════════
def _rf(res: str) -> str:
    return {"4K — 2160p":"[height<=2160]","1080p HD":"[height<=1080]",
            "720p HD":"[height<=720]","480p SD":"[height<=480]",
            "360p SD":"[height<=360]"}.get(res,"")

def auto_fmt(res: str, cont: str) -> str:
    if res == "Audio Only": return "bestaudio[ext=m4a]/bestaudio"
    r = _rf(res)
    if "MP4" in cont:
        return (f"bestvideo{r}[ext=mp4][vcodec^=avc]+bestaudio[ext=m4a]"
                f"/bestvideo{r}[ext=mp4]+bestaudio/bestvideo{r}+bestaudio/best{r}/best")
    elif "MKV" in cont:
        return f"bestvideo{r}+bestaudio/best{r}/best"
    else:
        return (f"bestvideo{r}[ext=webm]+bestaudio[ext=webm]"
                f"/bestvideo{r}+bestaudio/best{r}/best")

def manual_fmt(vid: str, aud: str, h: int = 1080) -> str:
    if not vid: return "bestvideo+bestaudio/best"
    if not aud: return f"{vid}/bestvideo[height<={h}]/best"
    return (f"{vid}+{aud}"
            f"/bestvideo[height<={h}][ext=mp4][vcodec^=avc]+bestaudio[ext=m4a]"
            f"/bestvideo[height<={h}]+bestaudio/best[height<={h}]/best")

def parse_fmts(info: dict):
    fmts = info.get("formats") or []
    muxed = {f["format_id"] for f in fmts
             if f.get("vcodec","none") not in ("none",None,"")
             and f.get("acodec","none") not in ("none",None,"")}

    seen, vraw = set(), []
    for f in fmts:
        if f["format_id"] in muxed: continue
        vc = f.get("vcodec","none")
        if not vc or vc=="none": continue
        h   = f.get("height") or 0
        fps = round(f.get("fps") or 0)
        tbr = f.get("tbr") or 0
        ext = f.get("ext","?")
        key = (h, fps, ext[:3])
        if key in seen: continue
        seen.add(key)
        lbl = (f"{h}p {fps}fps " if fps else f"{h}p ") + f"[{ext}/{vc[:6]}]" + (f" ~{tbr:.0f}k" if tbr else "")
        vraw.append((h, lbl.strip(), f["format_id"]))

    best_mux = next(
        (f for f in sorted(fmts,key=lambda x: x.get("height") or 0,reverse=True)
         if f["format_id"] in muxed and f.get("ext")=="mp4"), None)
    if best_mux:
        bh  = best_mux.get("height") or 720
        tbr = best_mux.get("tbr") or 0
        lbl = f"⚡ {bh}p pre-merged MP4 ~{tbr:.0f}k  (no ffmpeg needed)"
        vraw.append((99999, lbl, best_mux["format_id"]))

    vraw.sort(key=lambda x: x[0], reverse=True)
    real_h = {best_mux["format_id"]: (best_mux.get("height") or 720)} if best_mux else {}
    vopts = [(lbl, fid, real_h.get(fid, h)) for h,lbl,fid in vraw]

    seen_a, araw = set(), []
    for f in fmts:
        if f.get("vcodec","none") not in ("none",None,""): continue
        ac = f.get("acodec","none")
        if not ac or ac=="none": continue
        abr = f.get("abr") or f.get("tbr") or 0
        ext = f.get("ext","?")
        key = (round(abr/16)*16, ext)
        if key in seen_a: continue
        seen_a.add(key)
        lbl = f"~{abr:.0f} kbps  [{ext} / {ac[:8]}]"
        araw.append((abr, lbl, f["format_id"]))
    araw.sort(key=lambda x: x[0], reverse=True)
    aopts = [(lbl, fid, abr) for abr,lbl,fid in araw]
    return vopts, aopts

def safe_title(info: dict) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", info.get("title") or info.get("id") or "video")[:180]

def _spd(b: float) -> str:
    if b>=1_048_576: return f"{b/1_048_576:.1f} MB/s"
    if b>=1024:      return f"{b/1024:.0f} KB/s"
    return "…"
def _sz(b: int) -> str:
    if b>=1_073_741_824: return f"{b/1_073_741_824:.2f} GB"
    if b>=1_048_576:     return f"{b/1_048_576:.1f} MB"
    if b>=1024:          return f"{b/1024:.0f} KB"
    return f"{b} B"
def _eta(s: int) -> str:
    if not s: return "--"
    m,s2=divmod(int(s),60); h,m=divmod(m,60)
    return f"{h}h{m:02d}m" if h else f"{m}m{s2:02d}s"

# ══════════════════════════════════════════════════════════════════════════════
#  IMAGE HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def _vgrad(draw, x0,y0,x1,y1, c1, c2):
    steps = y1-y0
    for i in range(steps):
        t = i/max(steps-1,1)
        r=int(c1[0]+(c2[0]-c1[0])*t); g=int(c1[1]+(c2[1]-c1[1])*t); b=int(c1[2]+(c2[2]-c1[2])*t)
        draw.line([(x0,y0+i),(x1,y0+i)], fill=(r,g,b))

def mk_thumb() -> ctk.CTkImage:
    img=Image.new("RGB",(TW,TH)); d=ImageDraw.Draw(img)
    _vgrad(d,0,0,TW,TH,(8,11,22),(20,25,55))
    d.rectangle([0,0,TW-1,TH-1],outline=(40,50,100),width=1)
    cx,cy=TW//2,TH//2
    d.ellipse([cx-20,cy-20,cx+20,cy+20],fill=(80,60,180))
    d.ellipse([cx-19,cy-19,cx+19,cy+19],fill=(60,40,160))
    d.polygon([(cx-8,cy-12),(cx-8,cy+12),(cx+14,cy)],fill=(220,210,255))
    return ctk.CTkImage(img,img,size=(TW,TH))

def mk_done_thumb() -> ctk.CTkImage:
    img=Image.new("RGB",(TW,TH)); d=ImageDraw.Draw(img)
    _vgrad(d,0,0,TW,TH,(5,20,12),(10,35,20))
    d.rectangle([0,0,TW-1,TH-1],outline=(84,204,100),width=2)
    cx,cy=TW//2,TH//2
    d.ellipse([cx-18,cy-18,cx+18,cy+18],fill=(20,100,40))
    d.line([(cx-10,cy),(cx-3,cy+9),(cx+12,cy-10)],fill=(132,204,22),width=3)
    return ctk.CTkImage(img,img,size=(TW,TH))

def mk_err_thumb() -> ctk.CTkImage:
    img=Image.new("RGB",(TW,TH)); d=ImageDraw.Draw(img)
    _vgrad(d,0,0,TW,TH,(22,5,5),(40,10,10))
    d.rectangle([0,0,TW-1,TH-1],outline=(200,50,50),width=2)
    cx,cy=TW//2,TH//2
    d.ellipse([cx-18,cy-18,cx+18,cy+18],fill=(100,20,20))
    d.line([(cx-8,cy-8),(cx+8,cy+8)],fill=(239,68,68),width=3)
    d.line([(cx+8,cy-8),(cx-8,cy+8)],fill=(239,68,68),width=3)
    return ctk.CTkImage(img,img,size=(TW,TH))

def load_thumb(url: str) -> Optional[ctk.CTkImage]:
    try:
        import urllib.request
        data = urllib.request.urlopen(url, timeout=8).read()
        img  = Image.open(io.BytesIO(data)).convert("RGB").resize((TW,TH),Image.LANCZOS)
        # dark gradient overlay at bottom for text legibility
        ov = Image.new("RGBA",(TW,TH),(0,0,0,0))
        od = ImageDraw.Draw(ov)
        for i in range(TH//3):
            od.line([(0,TH-i-1),(TW,TH-i-1)],fill=(0,0,0,int(160*i/(TH//3))))
        img = Image.alpha_composite(img.convert("RGBA"),ov).convert("RGB")
        return ctk.CTkImage(img,img,size=(TW,TH))
    except Exception:
        return None

# ══════════════════════════════════════════════════════════════════════════════
#  YT-DLP WRAPPERS
# ══════════════════════════════════════════════════════════════════════════════
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")

def _base_opts(out: str, title: str, hook=None) -> dict:
    o: Dict[str,Any] = {
        "outtmpl": str(Path(out)/f"{title}.%(ext)s"),
        "windowsfilenames": True,
        "retries": 15, "fragment_retries": 15, "file_access_retries": 5,
        "skip_unavailable_fragments": False,
        "concurrent_fragment_downloads": 1,
        "http_chunk_size": 10*1024*1024,
        "retry_sleep_functions": {"http": lambda n: min(2**n,30),
                                   "fragment": lambda n: min(2**n,15)},
        "http_headers": {"User-Agent": _UA, "Accept-Language": "en-US,en;q=0.9"},
        "merge_output_format": "mp4",
        "keepvideo": False, "quiet": True, "no_warnings": True,
        "postprocessors": [{"key":"FFmpegMetadata","add_chapters":True}],
    }
    if hook: o["progress_hooks"] = [hook]
    if FFMPEG: o["ffmpeg_location"] = str(Path(FFMPEG).parent)
    return o

def _fetch_opts() -> dict:
    return {"quiet":True,"no_warnings":True,"http_headers":{"User-Agent":_UA}}

# ══════════════════════════════════════════════════════════════════════════════
#  CUSTOM WIDGETS
# ══════════════════════════════════════════════════════════════════════════════
class PasteBox(tk.Frame):
    """
    Full-featured URL input box.
    • Type URLs directly  —  keyboard input fully enabled
    • Ctrl+V / Cmd+V paste  |  right-click context menu  |  external Paste button
    • URLs highlighted cyan live as you type or paste
    • Placeholder hint shown when empty, clears on first keystroke
    • Enter adds a new line (one URL per line)
    """
    HINT = "Type or paste URLs here  (one per line)  —  YouTube · TikTok · Twitter/X · Instagram · and 1000+ more"

    def __init__(self, parent, **kw):
        super().__init__(parent, bg=B4,
                         highlightthickness=1, highlightbackground=BD, **kw)

        self.txt = tk.Text(
            self, height=3, wrap="word",
            bg=B4, fg=TX3, insertbackground=CYAN,
            relief="flat", bd=0, padx=12, pady=10,
            font=("Segoe UI", 11) if sys.platform == "win32" else ("SF Pro Text", 11),
            selectbackground=INDIGO, selectforeground=TX1,
            cursor="xterm", undo=True,
        )
        self.txt.pack(fill="both", expand=True)

        # Tag styling
        self.txt.tag_config("url",  foreground=CYAN)
        self.txt.tag_config("hint", foreground=TX3)
        self.txt.tag_config("body", foreground=TX1)

        # Insert placeholder
        self._set_hint()

        # ── Bindings ──────────────────────────────────────────────────────────
        # <KeyPress> fires BEFORE the character is inserted — perfect for clearing hint
        self.txt.bind("<KeyPress>",   self._on_keypress)
        # <KeyRelease> fires AFTER — use for re-highlighting
        self.txt.bind("<KeyRelease>", self._on_keyrelease)
        # Paste: let tk handle insertion natively, then re-highlight after
        self.txt.bind("<Control-v>",  lambda e: self.txt.after(10, self._recolor))
        self.txt.bind("<Control-V>",  lambda e: self.txt.after(10, self._recolor))
        self.txt.bind("<Command-v>",  lambda e: self.txt.after(10, self._recolor))
        self.txt.bind("<Command-V>",  lambda e: self.txt.after(10, self._recolor))
        self.txt.bind("<FocusIn>",    self._on_focus_in)
        self.txt.bind("<FocusOut>",   self._on_focus_out)

        # Right-click context menu
        self._menu = tk.Menu(
            self, tearoff=0, bg=B3, fg=TX1, bd=0, relief="flat",
            activebackground=VIOLET, activeforeground=TX1,
        )
        self._menu.add_command(label="  📋  Paste",       command=self._do_paste)
        self._menu.add_command(label="  ✂   Cut",         command=lambda: self.txt.event_generate("<<Cut>>"))
        self._menu.add_command(label="  📄  Copy",        command=lambda: self.txt.event_generate("<<Copy>>"))
        self._menu.add_separator()
        self._menu.add_command(label="  🔍  Select All",  command=lambda: self.txt.tag_add("sel","1.0","end"))
        self._menu.add_separator()
        self._menu.add_command(label="  🗑   Clear box",  command=self.clear)
        for w in (self, self.txt):
            w.bind("<Button-3>", self._show_menu, add="+")

        # Focus border glow
        self.txt.bind("<FocusIn>",  lambda e: self.config(highlightbackground=VIOLET), add="+")
        self.txt.bind("<FocusOut>", lambda e: self.config(highlightbackground=BD),     add="+")

    # ── Hint (placeholder) ────────────────────────────────────────────────────
    def _is_hint(self) -> bool:
        """True when the box only contains the placeholder text."""
        return self.txt.get("1.0","end").strip() == self.HINT.strip()

    def _set_hint(self):
        self.txt.delete("1.0", "end")
        self.txt.insert("1.0", self.HINT, "hint")

    def _clear_hint_if_needed(self):
        """Remove hint text so the user's real input starts clean."""
        if self._is_hint():
            self.txt.delete("1.0", "end")
            self.txt.config(fg=TX1)

    # ── Event handlers ────────────────────────────────────────────────────────
    def _on_keypress(self, event):
        """Fires BEFORE char is inserted — clear hint first so char lands in clean field."""
        # Ignore pure modifier keys
        if event.keysym in ("Shift_L","Shift_R","Control_L","Control_R",
                             "Alt_L","Alt_R","Super_L","Super_R",
                             "Caps_Lock","Num_Lock","Scroll_Lock"):
            return
        self._clear_hint_if_needed()

    def _on_keyrelease(self, _=None):
        """Fires AFTER char is inserted — re-colour everything."""
        if not self._is_hint():
            self._recolor()

    def _on_focus_in(self, _=None):
        # Select-all the hint so typing immediately replaces it (visual cue)
        if self._is_hint():
            self.txt.tag_add("sel", "1.0", "end")

    def _on_focus_out(self, _=None):
        content = self.txt.get("1.0", "end").strip()
        if not content:
            self._set_hint()
            self.config(highlightbackground=BD)

    # ── URL highlighting ──────────────────────────────────────────────────────
    def _recolor(self):
        """Repaint all text: normal body colour, URLs in cyan."""
        self.txt.tag_remove("url",  "1.0", "end")
        self.txt.tag_remove("body", "1.0", "end")
        self.txt.tag_remove("hint", "1.0", "end")
        content = self.txt.get("1.0", "end")
        self.txt.tag_add("body", "1.0", "end")
        for m in re.finditer(r"https?://\S+", content):
            self.txt.tag_add("url", f"1.0+{m.start()}c", f"1.0+{m.end()}c")

    # ── Context menu ──────────────────────────────────────────────────────────
    def _do_paste(self):
        self._clear_hint_if_needed()
        try:
            clip = self.txt.clipboard_get()
            self.txt.insert(tk.INSERT, clip)
            self._recolor()
        except Exception:
            pass

    def _show_menu(self, event):
        try:    self._menu.tk_popup(event.x_root, event.y_root)
        finally: self._menu.grab_release()

    # ── External API ─────────────────────────────────────────────────────────
    def paste_from_clipboard(self):
        """Called by the Paste & Add button — inserts clipboard, keeps existing content."""
        self._clear_hint_if_needed()
        try:
            clip = self.txt.clipboard_get()
            if not clip.strip():
                return
            cur = self.txt.get("1.0", "end-1c").strip()
            if cur:
                self.txt.insert("end", "\n" + clip.strip())
            else:
                self.txt.insert("1.0", clip.strip())
            self._recolor()
            self.txt.see("end")
        except Exception:
            pass

    def clear(self):
        self._set_hint()
        self.config(highlightbackground=BD)

    def get_urls(self) -> List[str]:
        if self._is_hint():
            return []
        raw = self.txt.get("1.0", "end")
        return [u.strip() for u in re.split(r"[\s,\n\r]+", raw)
                if u.strip().startswith("http")]


class PathDisplay(tk.Frame):
    """
    Read-only path display with Browse button.
    No typing allowed — only folder picker dialog.
    """
    def __init__(self, parent, initial: str, on_change, **kw):
        super().__init__(parent, bg=B1, **kw)
        self._path = initial
        self._on_change = on_change
        self.grid_columnconfigure(0, weight=1)

        self._lbl = tk.Label(self, text=self._shorten(initial),
                             bg=B4, fg=TX2, anchor="w",
                             relief="flat", padx=10, pady=7,
                             font=("Segoe UI",9) if sys.platform=="win32"
                                   else ("SF Pro Text",9),
                             cursor="arrow")
        self._lbl.grid(row=0, column=0, sticky="ew", padx=(0,6))

        btn = tk.Button(self, text=" Browse… ", bg=VIOLET, fg=TX1,
                        activebackground=INDIGO, activeforeground=TX1,
                        relief="flat", bd=0, cursor="hand2",
                        padx=10, pady=7,
                        font=("Segoe UI",9,"bold") if sys.platform=="win32"
                              else ("SF Pro Text",9,"bold"),
                        command=self._browse)
        btn.grid(row=0, column=1)
        btn.bind("<Enter>", lambda e: btn.config(bg=INDIGO))
        btn.bind("<Leave>", lambda e: btn.config(bg=VIOLET))

    def _shorten(self, p: str) -> str:
        return p if len(p)<=34 else "…"+p[-32:]

    def _browse(self):
        d = filedialog.askdirectory(initialdir=self._path)
        if d:
            self._path = d
            self._lbl.config(text=self._shorten(d))
            self._on_change(d)

    @property
    def path(self) -> str:
        return self._path


def mk_combo(parent, var: tk.StringVar, values: List[str],
             width: int = 230, height: int = 32) -> ctk.CTkComboBox:
    """
    Factory for read-only dropdowns.
    state='readonly' prevents any keyboard typing in the combo entry.
    """
    cb = ctk.CTkComboBox(
        parent, variable=var, values=values,
        state="readonly",                  # ← blocks all typing
        width=width, height=height,
        fg_color=B4,
        border_color=BD,
        border_width=1,
        button_color=VIOLET,
        button_hover_color=INDIGO,
        dropdown_fg_color=B3,
        dropdown_text_color=TX1,
        dropdown_hover_color=INDIGO,
        text_color=TX1,
        font=ctk.CTkFont(size=11),
        corner_radius=6,
    )
    return cb


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN APPLICATION
# ══════════════════════════════════════════════════════════════════════════════
class StreamSave(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP}  {VER}")
        self.geometry(f"{WW}x{WH}")
        self.minsize(1000, 660)
        self.configure(fg_color=B0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        try: self.iconbitmap("")
        except Exception: pass

        # App state
        self.items:      List[Item]      = []
        self.widgets:    Dict[str,dict]  = {}
        self.active:     Optional[Item]  = None
        self.running     = False
        self.stop_req    = False
        self.out_dir     = str(Path.home()/"Downloads")

        # Thread queues
        self.fetch_q = queue.Queue()
        self.dl_q    = queue.Queue()
        self.gui_q   = queue.Queue()
        self._maxseen = 0

        # Cached settings snapshot passed to worker (thread-safe)
        self._dl_settings: dict = {}

        threading.Thread(target=self._fetch_worker, daemon=True).start()
        threading.Thread(target=self._dl_worker,    daemon=True).start()

        self._build_sidebar()
        self._build_center()
        self._build_right()
        self.after(80, self._pump)

    # ══════════════════════════════════════════════════════════════════════════
    #  SIDEBAR
    # ══════════════════════════════════════════════════════════════════════════
    def _build_sidebar(self):
        sb = tk.Frame(self, bg=B1, width=SBW)
        sb.grid(row=0, column=0, sticky="nsew")
        sb.grid_propagate(False)
        sb.grid_columnconfigure(0, weight=1)
        sb.grid_rowconfigure(20, weight=1)   # pushes ffmpeg status to bottom
        self._sb = sb

        # ── Logo ──────────────────────────────────────────────────────────────
        logo = tk.Canvas(sb, height=76, bg=B1, highlightthickness=0)
        logo.grid(row=0, column=0, sticky="ew")
        logo.bind("<Configure>", lambda e: self._draw_logo(logo))
        self._logo = logo

        # ── Mode toggle ───────────────────────────────────────────────────────
        self._sec(sb, "DOWNLOAD MODE", 1)
        mode_f = tk.Frame(sb, bg=B3)
        mode_f.grid(row=2, column=0, padx=14, pady=(0,6), sticky="ew")
        mode_f.grid_columnconfigure((0,1), weight=1)

        self.mode_var = tk.StringVar(value="auto")
        self._auto_btn = self._toggle_btn(mode_f, "⚡  Auto", "auto", 0)
        self._man_btn  = self._toggle_btn(mode_f, "🎛  Manual", "manual", 1)
        self._refresh_mode_btns()

        # ── Auto settings ─────────────────────────────────────────────────────
        self._sec(sb, "FORMAT PRESETS", 3)
        self._auto_f = tk.Frame(sb, bg=B1)
        self._auto_f.grid(row=4, column=0, padx=14, pady=(0,4), sticky="ew")
        self._auto_f.grid_columnconfigure(0, weight=1)
        self._build_auto_panel(self._auto_f)

        # ── Manual hint ───────────────────────────────────────────────────────
        self._man_f = tk.Frame(sb, bg=B3)
        self._man_f.grid(row=4, column=0, padx=14, pady=(0,4), sticky="ew")
        tk.Label(self._man_f,
                 text="Each video card shows its own\nformat dropdowns once fetched.\nChoose per video before starting.",
                 bg=B3, fg=TX2, justify="left", padx=12, pady=10,
                 font=("Segoe UI",10) if sys.platform=="win32" else ("SF Pro Text",10)
                 ).pack(anchor="w")
        self._man_f.grid_remove()

        # ── Save location ─────────────────────────────────────────────────────
        self._sec(sb, "SAVE LOCATION", 5)
        self._path_disp = PathDisplay(sb, self.out_dir,
                                      on_change=lambda d: setattr(self,"out_dir",d))
        self._path_disp.grid(row=6, column=0, padx=14, pady=(0,6), sticky="ew")

        # ── ffmpeg status ─────────────────────────────────────────────────────
        self._sb_div(sb, 19)
        ff = tk.Frame(sb, bg=B1)
        ff.grid(row=20, column=0, padx=14, pady=(4,16), sticky="sw")
        col = LIME if FFMPEG else RED
        txt = "● ffmpeg  ready" if FFMPEG else "● ffmpeg  not found"
        tk.Label(ff, text=txt, bg=B1, fg=col,
                 font=("Segoe UI",9) if sys.platform=="win32" else ("SF Pro Text",9)
                 ).pack(anchor="w")
        if not FFMPEG:
            tk.Label(ff, text="  Install from: gyan.dev/ffmpeg/builds",
                     bg=B1, fg=TX3,
                     font=("Segoe UI",8) if sys.platform=="win32" else ("SF Pro Text",8)
                     ).pack(anchor="w")

    def _draw_logo(self, c):
        c.delete("all")
        w = max(c.winfo_width(), SBW)
        # Background gradient
        for i in range(76):
            t = i/75
            r=int(12+(8-12)*t); g=int(16+(11-16)*t); b=int(32+(22-32)*t)
            c.create_line(0,i,w,i,fill=f"#{r:02x}{g:02x}{b:02x}")
        # Glowing icon circle
        c.create_oval(14,18,52,56,fill="#1a0e3a",outline=VIOLET,width=2)
        c.create_oval(16,20,50,54,fill="#200e40",outline="")
        # Play triangle
        c.create_polygon(25,27,25,47,45,37,fill=VIOLET)
        c.create_polygon(26,28,26,46,43,37,fill="#9d7af0")
        # Title text
        c.create_text(62,30,anchor="w",text=APP,fill=TX1,
                      font=("Segoe UI",17,"bold") if sys.platform=="win32"
                            else ("SF Pro Text",17,"bold"))
        c.create_text(62,50,anchor="w",text=f"v{VER}  ·  Universal Downloader",
                      fill=TX3,
                      font=("Segoe UI",9) if sys.platform=="win32" else ("SF Pro Text",9))

    def _toggle_btn(self, parent, text, value, col):
        def _click():
            self.mode_var.set(value)
            self._on_mode()
        b = tk.Button(parent, text=text, relief="flat", bd=0,
                      cursor="hand2", command=_click, padx=8, pady=8,
                      font=("Segoe UI",11) if sys.platform=="win32" else ("SF Pro Text",11))
        b.grid(row=0, column=col, sticky="ew", padx=2, pady=4)
        return b

    def _refresh_mode_btns(self):
        v = self.mode_var.get()
        for btn, val in ((self._auto_btn,"auto"),(self._man_btn,"manual")):
            if val == v:
                btn.config(bg=VIOLET, fg=TX1, activebackground=INDIGO,
                           activeforeground=TX1, font=(
                               ("Segoe UI",11,"bold") if sys.platform=="win32"
                               else ("SF Pro Text",11,"bold")))
            else:
                btn.config(bg=B4, fg=TX2, activebackground=B5,
                           activeforeground=TX2,
                           font=("Segoe UI",11) if sys.platform=="win32"
                                 else ("SF Pro Text",11))
            btn.bind("<Enter>", lambda e,b=btn,vv=val:
                     b.config(bg=INDIGO if vv==self.mode_var.get() else B5))
            btn.bind("<Leave>", lambda e,b=btn,vv=val:
                     b.config(bg=VIOLET if vv==self.mode_var.get() else B4))

    def _on_mode(self):
        self._refresh_mode_btns()
        if self.mode_var.get()=="auto":
            self._auto_f.grid()
            self._man_f.grid_remove()
        else:
            self._auto_f.grid_remove()
            self._man_f.grid()
        # Refresh format visibility on all queue cards
        for iid in list(self.widgets):
            self._set_fmt_vis(iid)

    def _build_auto_panel(self, f):
        def lbl(txt, r):
            tk.Label(f, text=txt, bg=B1, fg=TX2,
                     font=("Segoe UI",9) if sys.platform=="win32" else ("SF Pro Text",9)
                     ).grid(row=r, column=0, sticky="w", pady=(8,2))

        lbl("Resolution  /  Quality", 0)
        self.res_var = tk.StringVar(value="1080p HD")
        mk_combo(f, self.res_var, RESOLUTIONS, 240, 32).grid(row=1,column=0,sticky="ew")

        lbl("Output container", 2)
        self.cont_var = tk.StringVar(value="MP4  (h264 + aac — recommended)")
        mk_combo(f, self.cont_var, CONTAINERS, 240, 32).grid(row=3,column=0,sticky="ew")

        lbl("Audio-only output format", 4)
        self.aext_var = tk.StringVar(value="MP3")
        mk_combo(f, self.aext_var, AUDIO_EXTS, 240, 32).grid(row=5,column=0,sticky="ew")

    def _sec(self, parent, text, row):
        f = tk.Frame(parent, bg=B1)
        f.grid(row=row, column=0, sticky="ew", pady=(12,3))
        tk.Frame(f, bg=BD, height=1).pack(fill="x", padx=14, pady=(0,5))
        tk.Label(f, text=text, bg=B1, fg=TX3, padx=14,
                 font=("Segoe UI",8,"bold") if sys.platform=="win32"
                       else ("SF Pro Text",8,"bold")).pack(anchor="w")

    def _sb_div(self, p, row):
        tk.Frame(p, bg=BD, height=1).grid(row=row, column=0, padx=14, pady=4, sticky="ew")

    # ══════════════════════════════════════════════════════════════════════════
    #  CENTER PANEL
    # ══════════════════════════════════════════════════════════════════════════
    def _build_center(self):
        ctr = tk.Frame(self, bg=B2)
        ctr.grid(row=0, column=1, sticky="nsew")
        ctr.grid_columnconfigure(0, weight=1)
        ctr.grid_rowconfigure(1, weight=1)
        self._ctr = ctr

        # ── URL input card ────────────────────────────────────────────────────
        url_card = tk.Frame(ctr, bg=B3,
                            highlightthickness=1, highlightbackground=BD)
        url_card.grid(row=0, column=0, padx=12, pady=(12,6), sticky="ew")
        url_card.grid_columnconfigure(0, weight=1)

        # Header row
        hdr = tk.Frame(url_card, bg=B3)
        hdr.grid(row=0, column=0, columnspan=2, sticky="ew", padx=12, pady=(10,4))
        tk.Label(hdr, text="ADD TO QUEUE", bg=B3, fg=TX3,
                 font=("Segoe UI",8,"bold") if sys.platform=="win32"
                       else ("SF Pro Text",8,"bold")).pack(side="left")
        tk.Label(hdr, text="  ·  YouTube, TikTok, Twitter/X, Instagram & 1000+ sites",
                 bg=B3, fg=TX3,
                 font=("Segoe UI",8) if sys.platform=="win32"
                       else ("SF Pro Text",8)).pack(side="left")

        # Paste box
        self._paste_box = PasteBox(url_card)
        self._paste_box.grid(row=1, column=0, padx=(12,8), pady=(0,10), sticky="ew")

        # Button column
        btns = tk.Frame(url_card, bg=B3)
        btns.grid(row=1, column=1, padx=(0,12), pady=(0,10), sticky="ns")
        self._btn(btns, "▶ Paste & Add", VIOLET, INDIGO,
                  self._paste_add, bold=True).pack(pady=(0,6), fill="x")
        self._btn(btns, "Add URLs",      B4,     B5,
                  self._add_urls).pack(fill="x")

        # ── Queue scroll area ─────────────────────────────────────────────────
        qwrap = tk.Frame(ctr, bg=B2)
        qwrap.grid(row=1, column=0, padx=12, pady=(0,6), sticky="nsew")
        qwrap.grid_columnconfigure(0, weight=1)
        qwrap.grid_rowconfigure(1, weight=1)

        # Queue header bar
        qhdr = tk.Frame(qwrap, bg=B2)
        qhdr.grid(row=0, column=0, sticky="ew", pady=(0,4))
        self._qlbl = tk.Label(qhdr, text="Queue  ·  empty", bg=B2, fg=TX3,
                              font=("Segoe UI",9,"bold") if sys.platform=="win32"
                                    else ("SF Pro Text",9,"bold"))
        self._qlbl.pack(side="left", padx=2)

        # Canvas + scrollbar
        scroll_wrap = tk.Frame(qwrap, bg=B2)
        scroll_wrap.grid(row=1, column=0, sticky="nsew")
        scroll_wrap.grid_columnconfigure(0, weight=1)
        scroll_wrap.grid_rowconfigure(0, weight=1)

        self._qcanvas = tk.Canvas(scroll_wrap, bg=B2, highlightthickness=0, bd=0)
        vsb = tk.Scrollbar(scroll_wrap, orient="vertical",
                           command=self._qcanvas.yview, bg=B3,
                           troughcolor=B2, activebackground=VIOLET)
        self._qcanvas.configure(yscrollcommand=vsb.set)
        vsb.grid(row=0, column=1, sticky="ns")
        self._qcanvas.grid(row=0, column=0, sticky="nsew")

        self._qinner = tk.Frame(self._qcanvas, bg=B2)
        self._qwin   = self._qcanvas.create_window((0,0), window=self._qinner, anchor="nw")
        self._qinner.bind("<Configure>",
            lambda e: self._qcanvas.configure(scrollregion=self._qcanvas.bbox("all")))
        self._qcanvas.bind("<Configure>",
            lambda e: self._qcanvas.itemconfig(self._qwin, width=e.width))
        for seq in ("<MouseWheel>","<Button-4>","<Button-5>"):
            self._qcanvas.bind_all(seq, self._scroll)

        self._empty_lbl = tk.Label(self._qinner,
                                    text="Queue is empty\n\nPaste URLs above to get started",
                                    bg=B2, fg=TX3, justify="center",
                                    font=("Segoe UI",14) if sys.platform=="win32"
                                          else ("SF Pro Text",14))
        self._empty_lbl.pack(pady=80)

        # ── Controls bar ──────────────────────────────────────────────────────
        ctrl = tk.Frame(ctr, bg=B3, highlightthickness=1, highlightbackground=BD)
        ctrl.grid(row=2, column=0, padx=12, pady=(0,12), sticky="ew")
        ctrl.grid_columnconfigure(2, weight=1)

        self._start_btn = self._btn(ctrl, "▶   Start All",  TEAL,  "#0d9488",
                                    self._start, bold=True, h=42)
        self._start_btn.grid(row=0, column=0, padx=(12,6), pady=10)

        self._stop_btn  = self._btn(ctrl, "■   Stop",        B4,    B4,
                                    self._stop, bold=True, h=42)
        self._stop_btn.config(fg=TX3, state="disabled")
        self._stop_btn.grid(row=0, column=1, padx=6, pady=10)

        self._status_lbl = tk.Label(ctrl, text="", bg=B3, fg=TX3,
                                    font=("Segoe UI",10) if sys.platform=="win32"
                                          else ("SF Pro Text",10))
        self._status_lbl.grid(row=0, column=2, padx=8, sticky="e")

        self._btn(ctrl, "Clear Queue", B4, B5,
                  self._clear, h=42).grid(row=0, column=3, padx=(6,12), pady=10)

    def _scroll(self, e):
        if e.num==4: self._qcanvas.yview_scroll(-1,"units")
        elif e.num==5: self._qcanvas.yview_scroll(1,"units")
        else: self._qcanvas.yview_scroll(-1*(e.delta//120),"units")

    def _btn(self, parent, text, bg, hov, cmd, bold=False, h=34, w=None):
        f = ("Segoe UI",10,"bold") if bold and sys.platform=="win32" else \
            ("SF Pro Text",10,"bold") if bold else \
            ("Segoe UI",10) if sys.platform=="win32" else ("SF Pro Text",10)
        kw = {}
        if w: kw["width"] = w
        b = tk.Button(parent, text=text, bg=bg, fg=TX1,
                      activebackground=hov, activeforeground=TX1,
                      relief="flat", bd=0, font=f, cursor="hand2",
                      padx=16, pady=(h-20)//2, command=cmd, **kw)
        b.bind("<Enter>", lambda e,_b=b,_h=hov: _b.config(bg=_h))
        b.bind("<Leave>", lambda e,_b=b,_bg=bg: _b.config(bg=_bg))
        return b

    # ══════════════════════════════════════════════════════════════════════════
    #  RIGHT PANEL
    # ══════════════════════════════════════════════════════════════════════════
    def _build_right(self):
        rp = tk.Frame(self, bg=B1, width=RPW)
        rp.grid(row=0, column=2, sticky="nsew")
        rp.grid_propagate(False)
        rp.grid_columnconfigure(0, weight=1)
        rp.grid_rowconfigure(9, weight=1)
        self._rp = rp

        # Gradient accent stripe at top
        stripe = tk.Canvas(rp, height=4, bg=B1, highlightthickness=0)
        stripe.grid(row=0, column=0, sticky="ew")
        stripe.bind("<Configure>", lambda e: self._draw_stripe(stripe))

        tk.Label(rp, text="NOW DOWNLOADING", bg=B1, fg=TX3, padx=16,
                 font=("Segoe UI",8,"bold") if sys.platform=="win32"
                       else ("SF Pro Text",8,"bold")
                 ).grid(row=1, column=0, sticky="w", pady=(12,4))

        # Thumbnail
        self._thumb = ctk.CTkLabel(rp, text="", image=mk_thumb(),
                                    width=TW, height=TH)
        self._thumb.grid(row=2, column=0, padx=16, pady=(0,8), sticky="w")

        # Title
        self._now_title = tk.Label(rp, text="—", bg=B1, fg=TX1, anchor="w",
                                    wraplength=RPW-32, justify="left",
                                    font=("Segoe UI",11,"bold") if sys.platform=="win32"
                                          else ("SF Pro Text",11,"bold"))
        self._now_title.grid(row=3, column=0, padx=16, pady=(0,4), sticky="ew")

        # Progress bar (CTkProgressBar — simpler, more reliable)
        self._prog = ctk.CTkProgressBar(rp, height=10,
                                         fg_color=B4, progress_color=VIOLET,
                                         corner_radius=5)
        self._prog.set(0)
        self._prog.grid(row=4, column=0, padx=16, pady=(4,4), sticky="ew")

        # Stats row
        sf = tk.Frame(rp, bg=B1)
        sf.grid(row=5, column=0, padx=16, pady=(2,2), sticky="ew")
        sf.grid_columnconfigure((0,1,2), weight=1)
        self._lpct   = self._rstat(sf, "0%",    0, CYAN)
        self._lspd   = self._rstat(sf, "—",     1, TX2)
        self._leta   = self._rstat(sf, "ETA —", 2, TX2)
        self._lsz    = tk.Label(rp, text="", bg=B1, fg=TX3, padx=16,
                                 font=("Segoe UI",9) if sys.platform=="win32"
                                       else ("SF Pro Text",9))
        self._lsz.grid(row=6, column=0, sticky="w")

        tk.Frame(rp, bg=BD, height=1).grid(row=7, column=0, padx=12, pady=8, sticky="ew")

        # Log header row with title + clear button
        log_hdr = tk.Frame(rp, bg=B1)
        log_hdr.grid(row=8, column=0, sticky="ew", padx=12, pady=(0,2))
        log_hdr.grid_columnconfigure(0, weight=1)

        tk.Label(log_hdr, text="ACTIVITY LOG", bg=B1, fg=TX3, padx=4,
                 font=("Segoe UI",8,"bold") if sys.platform=="win32"
                       else ("SF Pro Text",8,"bold")
                 ).grid(row=0, column=0, sticky="w")

        clr_btn = tk.Button(log_hdr, text="Clear", bg=B1, fg=TX3,
                            activebackground=B4, activeforeground=TX2,
                            relief="flat", bd=0, padx=6, pady=2,
                            cursor="hand2",
                            font=("Segoe UI",8) if sys.platform=="win32"
                                  else ("SF Pro Text",8),
                            command=self._clear_log)
        clr_btn.grid(row=0, column=1, sticky="e")
        clr_btn.bind("<Enter>", lambda e: clr_btn.config(fg=TX1))
        clr_btn.bind("<Leave>", lambda e: clr_btn.config(fg=TX3))

        log_wrap = tk.Frame(rp, bg=B3,
                            highlightthickness=1, highlightbackground=BD)
        log_wrap.grid(row=9, column=0, padx=12, pady=(0,12), sticky="nsew")
        log_wrap.grid_columnconfigure(0, weight=1)
        log_wrap.grid_rowconfigure(0, weight=1)

        self._log = tk.Text(
            log_wrap, bg=B3, fg=TX2, relief="flat", bd=0,
            padx=10, pady=8, state="disabled", wrap="word",
            font=("Consolas",9) if sys.platform=="win32" else ("Menlo",9),
            selectbackground=INDIGO, selectforeground=TX1,
            cursor="arrow", spacing1=1, spacing3=2,
        )
        self._log.grid(row=0, column=0, sticky="nsew")
        lsb = tk.Scrollbar(log_wrap, orient="vertical",
                           command=self._log.yview,
                           bg=B3, troughcolor=B3, activebackground=VIOLET,
                           relief="flat", bd=0, width=8)
        self._log.config(yscrollcommand=lsb.set)
        lsb.grid(row=0, column=1, sticky="ns")

        # ── Rich tag definitions ──────────────────────────────────────────────
        # Timestamps
        self._log.tag_config("ts",      foreground=TX3,   font=("Consolas",8) if sys.platform=="win32" else ("Menlo",8))
        # Event categories
        self._log.tag_config("ok",      foreground=LIME,  font=("Consolas",9,"bold") if sys.platform=="win32" else ("Menlo",9,"bold"))
        self._log.tag_config("err",     foreground=RED,   font=("Consolas",9,"bold") if sys.platform=="win32" else ("Menlo",9,"bold"))
        self._log.tag_config("info",    foreground=CYAN)
        self._log.tag_config("warn",    foreground=AMBER)
        self._log.tag_config("start",   foreground=VIOLET, font=("Consolas",9,"bold") if sys.platform=="win32" else ("Menlo",9,"bold"))
        self._log.tag_config("fetch",   foreground=BLUE)
        self._log.tag_config("speed",   foreground=TEAL,  font=("Consolas",8) if sys.platform=="win32" else ("Menlo",8))
        self._log.tag_config("done_big",foreground=LIME,  font=("Consolas",10,"bold") if sys.platform=="win32" else ("Menlo",10,"bold"))
        self._log.tag_config("sep",     foreground=BD)
        self._log.tag_config("title",   foreground=TX1,   font=("Consolas",9,"bold") if sys.platform=="win32" else ("Menlo",9,"bold"))
        self._log.tag_config("url_log", foreground="#6b8cff", underline=False)
        self._log.tag_config("dim",     foreground=TX3,   font=("Consolas",8) if sys.platform=="win32" else ("Menlo",8))

        # ── Startup banner ────────────────────────────────────────────────────
        self._log_banner()

    def _draw_stripe(self, c):
        c.delete("all")
        w = max(c.winfo_width(), RPW)
        for i in range(w):
            t = i/max(w-1,1)
            r=int(GLOW_V[0]+(GLOW_C[0]-GLOW_V[0])*t)
            g=int(GLOW_V[1]+(GLOW_C[1]-GLOW_V[1])*t)
            b=int(GLOW_V[2]+(GLOW_C[2]-GLOW_V[2])*t)
            c.create_line(i,0,i,4,fill=f"#{r:02x}{g:02x}{b:02x}")

    def _rstat(self, p, text, col, fg):
        l = tk.Label(p, text=text, bg=B1, fg=fg,
                     font=("Segoe UI",10,"bold") if sys.platform=="win32"
                           else ("SF Pro Text",10,"bold"))
        l.grid(row=0, column=col, sticky="w")
        return l

    # ══════════════════════════════════════════════════════════════════════════
    #  QUEUE ROW
    # ══════════════════════════════════════════════════════════════════════════
    def _add_row(self, item: Item):
        try: self._empty_lbl.pack_forget()
        except Exception: pass

        # Outer card frame with coloured left accent
        card = tk.Frame(self._qinner, bg=B3,
                        highlightthickness=1, highlightbackground=BD)
        card.pack(fill="x", padx=6, pady=4)
        card.grid_columnconfigure(2, weight=1)

        # Left accent stripe (colour changes with status)
        accent = tk.Frame(card, bg=VIOLET, width=4)
        accent.grid(row=0, column=0, rowspan=5, sticky="ns")

        # Thumbnail
        ph = mk_thumb()
        thumb = ctk.CTkLabel(card, text="", image=ph, width=TW, height=TH)
        thumb.grid(row=0, column=1, rowspan=3, padx=(8,10), pady=8)
        thumb._img = ph   # keep reference

        # Status badge
        sbadge = tk.Label(card, text="● PENDING", bg=B3, fg=SCOL["PENDING"],
                          font=("Segoe UI",8,"bold") if sys.platform=="win32"
                                else ("SF Pro Text",8,"bold"))
        sbadge.grid(row=0, column=2, padx=4, pady=(10,0), sticky="w")

        # Remove button
        rm = tk.Button(card, text=" ✕ ", bg=B3, fg=TX3, relief="flat", bd=0,
                       cursor="hand2", command=lambda i=item.iid: self._remove(i),
                       font=("Segoe UI",11) if sys.platform=="win32"
                             else ("SF Pro Text",11),
                       activebackground=RED, activeforeground=TX1)
        rm.grid(row=0, column=3, padx=(4,8), pady=(8,0), sticky="ne")
        rm.bind("<Enter>", lambda e: rm.config(bg=RED, fg=TX1))
        rm.bind("<Leave>", lambda e: rm.config(bg=B3,  fg=TX3))

        # Title
        tlbl = tk.Label(card, text=item.url[:75], bg=B3, fg=TX1,
                        anchor="w", justify="left", wraplength=340,
                        font=("Segoe UI",11,"bold") if sys.platform=="win32"
                              else ("SF Pro Text",11,"bold"))
        tlbl.grid(row=1, column=2, columnspan=2, padx=4, pady=(0,1), sticky="ew")

        # Meta (duration, size)
        meta = tk.Label(card, text="", bg=B3, fg=TX3, anchor="w",
                        font=("Segoe UI",9) if sys.platform=="win32"
                              else ("SF Pro Text",9))
        meta.grid(row=2, column=2, columnspan=2, padx=4, pady=(0,2), sticky="w")

        # Format dropdowns row (manual mode, shown when READY)
        fmt_row = tk.Frame(card, bg=B3)
        fmt_row.grid(row=3, column=1, columnspan=3, padx=(8,8), pady=(0,6), sticky="ew")
        fmt_row.grid_columnconfigure((0,1), weight=1)

        v_var = tk.StringVar(value="Select video quality…")
        a_var = tk.StringVar(value="Select audio quality…")

        v_cb = mk_combo(fmt_row, v_var, ["Select video quality…"],
                        width=230, height=28)
        v_cb.grid(row=0, column=0, padx=(0,4), sticky="ew")

        a_cb = mk_combo(fmt_row, a_var, ["Select audio quality…"],
                        width=195, height=28)
        a_cb.grid(row=0, column=1, padx=(0,4), sticky="ew")

        # Progress strip at the very bottom of the card
        prog_strip = ctk.CTkProgressBar(card, height=4,
                                         fg_color=BD, progress_color=VIOLET,
                                         corner_radius=0)
        prog_strip.set(0)
        prog_strip.grid(row=4, column=0, columnspan=4, sticky="ew", padx=0, pady=0)
        prog_strip.grid_remove()

        # Store all widget refs
        self.widgets[item.iid] = {
            "card": card, "accent": accent, "thumb": thumb,
            "status": sbadge, "title": tlbl, "meta": meta,
            "fmt_row": fmt_row, "v_var": v_var, "a_var": a_var,
            "v_cb": v_cb, "a_cb": a_cb,
            "prog": prog_strip,
        }
        # Set initial format row visibility
        self._set_fmt_vis(item.iid)

    def _set_fmt_vis(self, iid: str):
        ws   = self.widgets.get(iid)
        item = next((i for i in self.items if i.iid==iid), None)
        if not ws or not item: return
        show = (self.mode_var.get()=="manual" and item.status=="READY")
        if show: ws["fmt_row"].grid()
        else:    ws["fmt_row"].grid_remove()

    # ══════════════════════════════════════════════════════════════════════════
    #  QUEUE OPERATIONS
    # ══════════════════════════════════════════════════════════════════════════
    def _paste_add(self):
        """Read clipboard, populate box, then add."""
        try:
            clip = self.clipboard_get()
            if clip.strip():
                self._paste_box._insert(clip)
        except Exception:
            pass
        self._add_urls()

    def _add_urls(self):
        urls = self._paste_box.get_urls()
        if not urls:
            messagebox.showinfo(APP,
                "No valid URLs found.\n\n"
                "Make sure each URL starts with  http://  or  https://\n\n"
                "Use Ctrl+V or the Paste & Add button to paste from clipboard.",
                parent=self)
            return
        added = 0
        for u in urls:
            if any(i.url==u for i in self.items): continue
            item = Item(url=u)
            self.items.append(item)
            self._add_row(item)
            self.fetch_q.put(item)
            added += 1
        self._paste_box.clear()
        self._upd_count()
        self._wlog(f"Queued {added} URL{'s' if added!=1 else ''}  —  fetching info…", "info")

    def _remove(self, iid: str):
        self.items = [i for i in self.items if i.iid!=iid]
        ws = self.widgets.pop(iid, None)
        if ws:
            try: ws["card"].destroy()
            except Exception: pass
        self._upd_count()
        if not self.items:
            self._empty_lbl.pack(pady=80)

    def _clear(self):
        if self.running:
            messagebox.showwarning(APP, "Stop the download first.", parent=self)
            return
        for ws in self.widgets.values():
            try: ws["card"].destroy()
            except Exception: pass
        self.widgets.clear()
        self.items.clear()
        self._upd_count()
        self._empty_lbl.pack(pady=80)

    def _upd_count(self):
        n    = len(self.items)
        done = sum(1 for i in self.items if i.status=="DONE")
        ready= sum(1 for i in self.items if i.status=="READY")
        if n==0:   txt = "Queue  ·  empty"
        elif done: txt = f"Queue  ·  {n} items  ·  {done} done  ·  {ready} ready"
        else:      txt = f"Queue  ·  {n} items  ·  {ready} ready"
        self._qlbl.config(text=txt)
        self._status_lbl.config(text=f"{ready} ready  ·  {done} done" if n else "")

    # ══════════════════════════════════════════════════════════════════════════
    #  BACKGROUND WORKERS
    # ══════════════════════════════════════════════════════════════════════════
    def _fetch_worker(self):
        while True:
            item: Item = self.fetch_q.get()
            self.gui_q.put({"t":"status","iid":item.iid,"s":"FETCHING"})
            self.gui_q.put({"t":"log","msg":f"Fetching: {item.url[:55]}","tag":"fetch"})
            try:
                with yt_dlp.YoutubeDL(_fetch_opts()) as ydl:
                    info = ydl.extract_info(item.url, download=False)
                # Handle playlists — use first entry
                if info.get("_type")=="playlist":
                    entries = list(info.get("entries") or [])
                    if entries:
                        first = entries[0]
                        if not first.get("formats"):
                            eu = first.get("webpage_url") or first.get("url","")
                            if eu:
                                with yt_dlp.YoutubeDL(_fetch_opts()) as y2:
                                    first = y2.extract_info(eu, download=False)
                        info = first
                item.info      = info
                item.title     = info.get("title") or item.url
                item.dur       = info.get("duration") or 0
                item.thumb_url = info.get("thumbnail") or ""
                item.vopts, item.aopts = parse_fmts(info)
                thumb = load_thumb(item.thumb_url) if item.thumb_url else None
                self.gui_q.put({"t":"fetched","iid":item.iid,"title":item.title,
                                "dur":item.dur,"thumb":thumb,
                                "vopts":item.vopts,"aopts":item.aopts})
            except Exception as e:
                self.gui_q.put({"t":"status","iid":item.iid,
                                "s":"ERROR","msg":str(e)[:220]})
                self.gui_q.put({"t":"log","msg":f"Fetch failed: {str(e)[:80]}","tag":"err"})

    def _dl_worker(self):
        while True:
            payload = self.dl_q.get()
            item:    Item = payload["item"]
            settings:dict = payload["settings"]   # snapshot, thread-safe

            if self.stop_req:
                self.gui_q.put({"t":"status","iid":item.iid,"s":"CANCELLED"})
                self.gui_q.put({"t":"dl_done"})
                continue

            self.gui_q.put({"t":"active","iid":item.iid})
            self.gui_q.put({"t":"status","iid":item.iid,"s":"DOWNLOADING"})
            self.gui_q.put({"t":"dl_start","iid":item.iid})
            self._maxseen = 0

            out   = settings["out_dir"]
            Path(out).mkdir(parents=True, exist_ok=True)
            title = safe_title(item.info) if item.info else "video"

            def make_hook(it):
                def hook(d):
                    if self.stop_req:
                        raise yt_dlp.utils.DownloadError("Stopped")
                    if d.get("status")=="downloading":
                        dl  = d.get("downloaded_bytes",0)
                        raw = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                        self._maxseen = max(self._maxseen, raw)
                        pct = min(dl/self._maxseen,1.0) if self._maxseen else 0
                        spd = d.get("speed") or 0
                        eta = d.get("eta") or 0
                        self.gui_q.put({"t":"progress","iid":it.iid,
                                        "pct":pct,"spd":spd,
                                        "eta":eta,
                                        "dl":dl,"tot":self._maxseen})
                        # Log speed every ~5 seconds via a flag on the item
                        now = time.time()
                        if not hasattr(it,"_last_log_t") or now - it._last_log_t >= 5:
                            it._last_log_t = now
                            if spd > 0:
                                self.gui_q.put({"t":"progress_log",
                                                "spd":spd,"eta":eta,
                                                "pct":pct,"dl":dl,"tot":self._maxseen})
                    elif d.get("status")=="finished":
                        self.gui_q.put({"t":"progress","iid":it.iid,"pct":1.0,
                                        "spd":0,"eta":0,
                                        "dl":self._maxseen,"tot":self._maxseen})
                return hook

            try:
                opts = _base_opts(out, title, make_hook(item))
                opts["format"] = item.fmt_str or "bestvideo+bestaudio/best"

                # Audio-only extraction
                if settings.get("audio_only"):
                    codec = settings.get("aext","mp3").lower().split()[0]
                    opts["postprocessors"] = [{
                        "key":"FFmpegExtractAudio",
                        "preferredcodec":codec, "preferredquality":"0"}]

                _PARTS.append(str(Path(out)/f"{title}*.part"))
                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.download([item.url])

                item.status = "DONE"
                self.gui_q.put({"t":"status","iid":item.iid,"s":"DONE"})
                self.gui_q.put({"t":"dl_done_item","iid":item.iid,"out":out})
            except Exception as e:
                msg = str(e)
                if self.stop_req:
                    self.gui_q.put({"t":"status","iid":item.iid,"s":"CANCELLED"})
                else:
                    item.status = "ERROR"
                    item.error  = msg
                    hint = ""
                    if "10054" in msg or "connection" in msg.lower():
                        hint = " (connection reset — will retry next time)"
                    elif "ffmpeg" in msg.lower():
                        hint = " (ffmpeg missing — install from gyan.dev/ffmpeg/builds)"
                    self.gui_q.put({"t":"status","iid":item.iid,
                                    "s":"ERROR","msg":(msg+hint)[:180]})
                    self.gui_q.put({"t":"log","msg":f"Error: {msg[:80]}{hint}","tag":"err"})
            finally:
                self.running = False
                self.gui_q.put({"t":"dl_done"})

    # ══════════════════════════════════════════════════════════════════════════
    #  CONTROLS
    # ══════════════════════════════════════════════════════════════════════════
    def _start(self):
        if self.running: return
        ready = [i for i in self.items if i.status=="READY"]
        if not ready:
            messagebox.showinfo(APP,
                "No videos are ready yet.\n\n"
                "Wait for the info fetching to complete\n"
                "(status will show  ● READY).",
                parent=self)
            return

        self.stop_req = False
        self._start_btn.config(state="disabled", bg="#0d4438", fg="#4a9a80")
        self._stop_btn.config(state="normal",  bg=RED, fg=TX1,
                              activebackground="#b91c1c", activeforeground=TX1)

        # Build settings SNAPSHOT now (thread-safe, no tkvar access in thread)
        res  = self.res_var.get()
        cont = self.cont_var.get()
        aext = self.aext_var.get()
        mode = self.mode_var.get()
        settings = {
            "out_dir":    self.out_dir,
            "audio_only": res=="Audio Only",
            "aext":       aext,
        }

        for item in ready:
            if mode=="auto":
                item.fmt_str = auto_fmt(res, cont)
            else:
                ws    = self.widgets.get(item.iid,{})
                v_lbl = ws["v_var"].get() if ws else ""
                a_lbl = ws["a_var"].get() if ws else ""
                v_id  = next((fid for lbl,fid,_ in item.vopts if lbl==v_lbl),"")
                a_id  = next((fid for lbl,fid,_ in item.aopts if lbl==a_lbl),"")
                h     = next((h   for lbl,_,h   in item.vopts if lbl==v_lbl),1080)
                item.fmt_str = manual_fmt(v_id, a_id, h)
            self.running = True
            self.dl_q.put({"item":item, "settings":settings})

    def _stop(self):
        self.stop_req = True
        self._wlog("Download stopped by user", "warn")
        self._wlog_sep()
        self._stop_btn.config(state="disabled", bg=B4, fg=TX3)

    # ══════════════════════════════════════════════════════════════════════════
    #  GUI MESSAGE PUMP
    # ══════════════════════════════════════════════════════════════════════════
    def _pump(self):
        try:
            while True: self._handle(self.gui_q.get_nowait())
        except queue.Empty:
            pass
        self.after(80, self._pump)

    def _handle(self, m: dict):
        t = m["t"]

        if t=="log":
            self._wlog(m["msg"], m.get("tag","info"))

        elif t=="dl_start":
            iid  = m["iid"]
            item = next((i for i in self.items if i.iid==iid), None)
            if item: self._wlog_dl_start(item)

        elif t=="dl_done_item":
            iid  = m["iid"]
            item = next((i for i in self.items if i.iid==iid), None)
            if item: self._wlog_done(item, m.get("out",""))

        elif t=="progress_log":
            self._wlog_progress(m["spd"], m["eta"], m["pct"], m["dl"], m["tot"])

        elif t=="status":
            iid = m["iid"]; s = m["s"]
            item = next((i for i in self.items if i.iid==iid), None)
            ws   = self.widgets.get(iid)
            if item: item.status = s
            if ws:
                col = SCOL.get(s, TX3)
                ws["status"].config(text=f"● {s}", fg=col)
                if s=="ERROR":
                    ws["card"].config(highlightbackground=RED)
                    ws["accent"].config(bg=RED)
                    err = m.get("msg","")
                    if err: ws["title"].config(text=f"❌  {err[:68]}", fg=RED)
                    ws["thumb"].configure(image=mk_err_thumb())
                elif s=="DONE":
                    ws["card"].config(highlightbackground=LIME)
                    ws["accent"].config(bg=LIME)
                    ws["prog"].configure(progress_color=LIME)
                    ws["prog"].set(1.0)
                    ws["prog"].grid()
                    ws["thumb"].configure(image=mk_done_thumb())
                elif s=="CANCELLED":
                    ws["card"].config(highlightbackground=TX3)
                    ws["accent"].config(bg=TX3)
                elif s=="DOWNLOADING":
                    ws["card"].config(highlightbackground=VIOLET)
                    ws["accent"].config(bg=VIOLET)
                    ws["prog"].grid()
                elif s=="READY":
                    ws["card"].config(highlightbackground=BLUE)
                    ws["accent"].config(bg=BLUE)
                    self._set_fmt_vis(iid)
                elif s=="FETCHING":
                    ws["card"].config(highlightbackground=AMBER)
                    ws["accent"].config(bg=AMBER)
            self._upd_count()

        elif t=="fetched":
            iid  = m["iid"]
            item = next((i for i in self.items if i.iid==iid), None)
            ws   = self.widgets.get(iid)
            if not item or not ws: return
            item.status = "READY"
            item.vopts  = m["vopts"]
            item.aopts  = m["aopts"]
            ws["status"].config(text="● READY", fg=SCOL["READY"])
            ws["title"].config(text=m["title"][:80], fg=TX1)
            ws["card"].config(highlightbackground=BLUE)
            ws["accent"].config(bg=BLUE)
            dur = m.get("dur",0)
            if dur:
                mm,ss=divmod(dur,60); hh,mm=divmod(mm,60)
                ws["meta"].config(
                    text=(f"{hh}h {mm:02d}m {ss:02d}s" if hh else f"{mm}m {ss:02d}s"))
            if m.get("thumb"):
                ws["thumb"].configure(image=m["thumb"])
                ws["thumb"]._img = m["thumb"]
            # Populate manual dropdowns (readonly)
            vlbls = [lbl for lbl,_,_ in item.vopts]
            albls = [lbl for lbl,_,_ in item.aopts]
            if vlbls:
                ws["v_cb"].configure(values=vlbls, state="readonly")
                ws["v_var"].set(vlbls[0])
            if albls:
                ws["a_cb"].configure(values=albls, state="readonly")
                ws["a_var"].set(albls[0])
            self._set_fmt_vis(iid)
            self._upd_count()
            dur = m.get("dur",0)
            dur_s = ""
            if dur:
                mm,ss=divmod(dur,60); hh,mm=divmod(mm,60)
                dur_s = f"  [{hh}h{mm:02d}m{ss:02d}s]" if hh else f"  [{mm}m{ss:02d}s]"
            self._wlog(f"Ready: {m['title'][:48]}{dur_s}", "ok")

        elif t=="active":
            iid  = m["iid"]
            item = next((i for i in self.items if i.iid==iid), None)
            self.active = item
            self._now_title.config(text=(item.title if item else "—")[:75])
            self._prog.set(0)
            self._prog.configure(progress_color=VIOLET)
            self._lpct.config(text="0%")
            self._lspd.config(text="—")
            self._leta.config(text="ETA —")
            self._lsz.config(text="")
            ws = self.widgets.get(iid,{})
            if ws.get("thumb"):
                try: self._thumb.configure(image=ws["thumb"]._img)
                except Exception: pass

        elif t=="progress":
            iid = m["iid"]
            pct = m["pct"]; spd = m["spd"]; eta = m["eta"]
            dl  = m["dl"];  tot = m["tot"]
            # Global progress bar — colour shifts violet→cyan
            t2   = pct
            r=int(GLOW_V[0]+(GLOW_C[0]-GLOW_V[0])*t2)
            g=int(GLOW_V[1]+(GLOW_C[1]-GLOW_V[1])*t2)
            b=int(GLOW_V[2]+(GLOW_C[2]-GLOW_V[2])*t2)
            self._prog.configure(progress_color=f"#{r:02x}{g:02x}{b:02x}")
            self._prog.set(pct)
            self._lpct.config(text=f"{pct*100:.1f}%")
            self._lspd.config(text=_spd(spd) if spd else "—")
            self._leta.config(text=f"ETA {_eta(eta)}")
            self._lsz.config(text=f"{_sz(dl)} / {_sz(tot)}" if tot else _sz(dl))
            # Per-item strip
            ws = self.widgets.get(iid,{})
            if ws.get("prog"):
                ws["prog"].set(pct)

        elif t=="dl_done":
            self.running = False
            self._start_btn.config(state="normal", bg=TEAL, fg=TX1,
                                   activebackground="#0d9488", activeforeground=TX1)
            if not self.stop_req:
                more = [i for i in self.items if i.status=="READY"]
                if not more:
                    self._stop_btn.config(state="disabled", bg=B4, fg=TX3)
                    done = sum(1 for i in self.items if i.status=="DONE")
                    n    = len(self.items)
                    self._wlog(f"All done  —  {done}/{n} succeeded", "done_big")
                    self._wlog_sep()
            else:
                self._stop_btn.config(state="disabled", bg=B4, fg=TX3)

    # ══════════════════════════════════════════════════════════════════════════
    #  ACTIVITY LOG  —  rich formatted output
    # ══════════════════════════════════════════════════════════════════════════
    def _log_banner(self):
        """Print startup banner to log."""
        self._log.config(state="normal")
        self._log.insert("end", "─" * 38 + "\n", "sep")
        self._log.insert("end", f" ▶  {APP} v{VER}  ready\n", "start")
        self._log.insert("end", f" ffmpeg: ", "dim")
        if FFMPEG:
            self._log.insert("end", "found ✓\n", "ok")
        else:
            self._log.insert("end", "not found  (merge disabled)\n", "warn")
        self._log.insert("end", "─" * 38 + "\n", "sep")
        self._log.config(state="disabled")

    def _wlog(self, msg: str, tag: str = "info"):
        """
        Append one log line.
        tag: "ok" | "err" | "info" | "warn" | "start" | "fetch" |
             "speed" | "done_big" | "sep" | "title" | "dim"
        """
        ts = time.strftime("%H:%M:%S")
        # icon map
        icons = {
            "ok":      "✔ ",
            "err":     "✘ ",
            "info":    "  ",
            "warn":    "⚠ ",
            "start":   "▶ ",
            "fetch":   "↺ ",
            "speed":   "  ",
            "done_big":"★ ",
            "dim":     "  ",
            "title":   "  ",
        }
        icon = icons.get(tag, "  ")
        self._log.config(state="normal")
        self._log.insert("end", f" {ts} ", "ts")
        self._log.insert("end", icon + msg + "\n", tag if tag else "info")
        self._log.see("end")
        self._log.config(state="disabled")

    def _wlog_sep(self):
        """Insert a visual separator line."""
        self._log.config(state="normal")
        self._log.insert("end", " " + "─" * 34 + "\n", "sep")
        self._log.config(state="disabled")

    def _wlog_dl_start(self, item: "Item"):
        """Rich multi-line entry when a download begins."""
        self._log.config(state="normal")
        ts = time.strftime("%H:%M:%S")
        self._log.insert("end", f" {ts} ", "ts")
        self._log.insert("end", "▶ Starting download\n", "start")
        self._log.insert("end", f"   ", "dim")
        self._log.insert("end", item.title[:55] + "\n", "title")
        if item.fmt_str:
            self._log.insert("end", f"   fmt: {item.fmt_str[:50]}\n", "dim")
        self._log.see("end")
        self._log.config(state="disabled")

    def _wlog_progress(self, spd: float, eta: int, pct: float, dl: int, tot: int):
        """Compact speed/eta line — replaces previous progress line if exists."""
        if spd <= 0:
            return
        line = (f"  {pct*100:.0f}%  {_spd(spd)}  ETA {_eta(eta)}"
                f"  {_sz(dl)}/{_sz(tot)}" if tot else f"  {_sz(dl)}")
        self._log.config(state="normal")
        # Check if last line is a speed line; if so, overwrite it
        last = self._log.get("end-2l", "end-1c")
        if last.strip().startswith("→"):
            self._log.delete("end-2l", "end-1l")
        ts = time.strftime("%H:%M:%S")
        self._log.insert("end", f" {ts} ", "ts")
        self._log.insert("end", f"→{line}\n", "speed")
        self._log.see("end")
        self._log.config(state="disabled")

    def _wlog_done(self, item: "Item", out_dir: str):
        """Rich multi-line done entry."""
        self._log.config(state="normal")
        ts = time.strftime("%H:%M:%S")
        self._log.insert("end", f" {ts} ", "ts")
        self._log.insert("end", "★ Download complete\n", "done_big")
        self._log.insert("end", f"   ", "dim")
        self._log.insert("end", item.title[:55] + "\n", "title")
        self._log.insert("end", f"   → {out_dir}\n", "dim")
        self._wlog_sep()
        self._log.see("end")
        self._log.config(state="disabled")

    def _clear_log(self):
        self._log.config(state="normal")
        self._log.delete("1.0", "end")
        self._log_banner()
        self._log.config(state="disabled")

    def on_close(self):
        self.stop_req = True
        self.destroy()


# ── Entry ─────────────────────────────────────────────────────────────────────
def main():
    app = StreamSave()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()

if __name__ == "__main__":
    main()
