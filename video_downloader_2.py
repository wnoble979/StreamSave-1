#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════╗
║      Universal Video Downloader  —  powered by yt-dlp   ║
║  YouTube • TikTok • Twitter/X • Instagram & 1000+ sites  ║
╚══════════════════════════════════════════════════════════╝
Fixes in this version
  ✔ WinError 10054  — retry + backoff + chunk size + User-Agent header
  ✔ Size never stops growing — removed double postprocessor, fixed DASH display
  ✔ Windows format compatibility — prefers h264/AAC/MP4 (native playback)
  ✔ Fallback format chains — if exact format unavailable, picks best compat
  ✔ ffmpeg auto-detected in common Windows install locations
  ✔ Temp/part files cleaned up on crash or Ctrl+C
  ✔ NameError on audio_ext fixed (initialised at top of each session)
  ✔ Playlist entries cached — no duplicate network fetches
  ✔ Progress bar stable on Windows CMD and PowerShell
"""

import sys
import os
import re
import atexit
import shutil
import subprocess
import glob
from pathlib import Path

# ── Auto-install yt-dlp if missing ──────────────────────────────────────────
try:
    import yt_dlp
except ImportError:
    print("Installing yt-dlp …")
    cmd = [sys.executable, "-m", "pip", "install", "yt-dlp", "-q"]
    if sys.platform != "win32":
        cmd.append("--break-system-packages")
    subprocess.check_call(cmd)
    import yt_dlp

# ── Color support ────────────────────────────────────────────────────────────
def _has_color():
    if not sys.stdout.isatty():
        return False
    if os.name == "nt":
        return any(os.environ.get(v) for v in
                   ("WT_SESSION", "COLORTERM", "TERM_PROGRAM", "ANSICON"))
    return True

USE_COLOR = _has_color()

def _c(text, code):
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else str(text)

CYAN   = lambda t: _c(t, "96")
GREEN  = lambda t: _c(t, "92")
YELLOW = lambda t: _c(t, "93")
RED    = lambda t: _c(t, "91")
BOLD   = lambda t: _c(t, "1")
DIM    = lambda t: _c(t, "2")
DIV    = DIM("─" * 62)

# ── ffmpeg auto-detection ────────────────────────────────────────────────────
def find_ffmpeg():
    found = shutil.which("ffmpeg")
    if found:
        return found
    candidates = [
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "ffmpeg", "bin", "ffmpeg.exe"),
        os.path.join(os.environ.get("USERPROFILE",  ""), "ffmpeg", "bin", "ffmpeg.exe"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "ffmpeg.exe"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "ffmpeg"),
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None

FFMPEG_PATH = find_ffmpeg()

# ── Cleanup .part files on exit ──────────────────────────────────────────────
_part_patterns = []

def _cleanup():
    for pat in _part_patterns:
        for f in glob.glob(pat):
            try:
                os.remove(f)
            except OSError:
                pass

atexit.register(_cleanup)

# ── UI helpers ────────────────────────────────────────────────────────────────
def banner():
    print()
    print(CYAN(BOLD("╔══════════════════════════════════════════════════════════╗")))
    print(CYAN(BOLD("║   🎬  Universal Video Downloader  (yt-dlp)               ║")))
    print(CYAN(BOLD("║   YouTube, TikTok, Twitter/X, Instagram & 1000+ sites    ║")))
    print(CYAN(BOLD("╚══════════════════════════════════════════════════════════╝")))
    print()

def hr():
    print(DIV)

def ask(prompt, default=None):
    hint = f" [{default}]" if default is not None else ""
    try:
        raw = input(f"{BOLD('▶')} {prompt}{hint}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)
    return raw if raw else (str(default) if default is not None else "")

def choose(options, prompt="Enter number"):
    for i, (lbl, _) in enumerate(options, 1):
        print(f"  {GREEN(str(i).rjust(2))}.  {lbl}")
    print()
    while True:
        raw = ask(prompt, default=1)
        try:
            idx = int(raw)
            if 1 <= idx <= len(options):
                return options[idx - 1]
        except ValueError:
            pass
        print(RED(f"  Please enter 1-{len(options)}."))

# ── Progress bar ──────────────────────────────────────────────────────────────
_last_fn  = ""
_max_seen = 0   # largest total_bytes estimate seen — prevents "shrinking" display

def progress_hook(d):
    global _last_fn, _max_seen
    status = d.get("status")

    if status == "downloading":
        fname = Path(d.get("filename", "")).name
        if fname and fname != _last_fn:
            _last_fn  = fname
            _max_seen = 0
            short = fname[:55] + "..." if len(fname) > 55 else fname
            print(f"\n  {DIM('Downloading:')} {short}")

        downloaded = d.get("downloaded_bytes", 0)
        raw_total  = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
        _max_seen  = max(_max_seen, raw_total)     # never let displayed size shrink
        total      = _max_seen

        speed = d.get("speed") or 0
        eta   = d.get("eta")

        pct    = min((downloaded / total * 100) if total else 0, 100.0)
        filled = int(30 * pct / 100)
        bar    = GREEN("=" * filled) + DIM("-" * (30 - filled))

        if speed >= 1_048_576:
            sp = f"{speed / 1_048_576:.1f} MB/s"
        elif speed >= 1024:
            sp = f"{speed / 1024:.0f} KB/s"
        else:
            sp = "..."

        eta_s  = f"{int(eta)//60}m{int(eta)%60:02d}s" if eta else "--"
        dl_mb  = downloaded / 1_048_576
        tot_mb = total / 1_048_576
        size_s = f"{dl_mb:.1f}/{tot_mb:.1f}MB" if total else f"{dl_mb:.1f}MB"

        print(f"\r  [{bar}] {pct:5.1f}%  {size_s}  {sp}  ETA {eta_s}  ", end="", flush=True)

    elif status == "finished":
        print(f"\n  {GREEN('OK')} Segment done - post-processing ...")

    elif status == "error":
        print(f"\n  {RED('!!')} Segment error - will retry ...")

# ── Format parsing ────────────────────────────────────────────────────────────
def parse_formats(info):
    """
    Returns (video_opts, audio_opts).
    Each item: (label_string, meta_dict).
    meta_dict carries format_id, height, ext, vcodec etc. for building format strings.
    Windows-native codecs (h264/AAC/mp4) are marked clearly.
    """
    formats = info.get("formats") or []

    combined_ids = {
        f["format_id"] for f in formats
        if (f.get("vcodec", "none") not in ("none", None, ""))
        and (f.get("acodec", "none") not in ("none", None, ""))
    }

    # ── Video-only streams ────────────────────────────────────────────────────
    seen = set()
    video_raw = []
    for f in formats:
        if f["format_id"] in combined_ids:
            continue
        vcodec = f.get("vcodec", "none")
        if not vcodec or vcodec == "none":
            continue
        h   = f.get("height") or 0
        fps = round(f.get("fps") or 0)
        tbr = f.get("tbr") or 0
        ext = f.get("ext", "?")
        key = (h, fps, ext[:3])
        if key in seen:
            continue
        seen.add(key)

        is_native = (ext == "mp4" and vcodec.startswith("avc"))
        tag   = GREEN("  [Windows native]") if is_native else DIM("  [needs ffmpeg]")
        fps_s = f" {fps}fps" if fps else ""
        tbr_s = f"  ~{tbr:.0f}kbps" if tbr else ""
        label = f"{h}p{fps_s}  [{ext}/{vcodec[:8]}]{tbr_s}{tag}"
        meta  = {"format_id": f["format_id"], "height": h, "ext": ext,
                 "vcodec": vcodec, "fps": fps, "combined": False}
        video_raw.append((h, label, meta))

    video_raw.sort(key=lambda x: x[0], reverse=True)
    video_opts = [(lbl, m) for _, lbl, m in video_raw]

    # ── Best combined MP4 (fastest — no ffmpeg merge needed) ─────────────────
    best_mux = None
    for f in sorted(formats, key=lambda x: x.get("height") or 0, reverse=True):
        if f["format_id"] in combined_ids and f.get("ext") == "mp4":
            best_mux = f
            break
    if best_mux:
        h   = best_mux.get("height") or "?"
        tbr = best_mux.get("tbr") or 0
        tbr_s = f"  ~{tbr:.0f}kbps" if tbr else ""
        label = (f"** {h}p  [mp4 pre-merged — fastest, no ffmpeg]{tbr_s}"
                 + GREEN("  [Windows native]"))
        meta  = {
            "format_id": best_mux["format_id"],
            "height":    best_mux.get("height") or 720,
            "ext":       "mp4",
            "vcodec":    best_mux.get("vcodec", ""),
            "fps":       best_mux.get("fps") or 0,
            "combined":  True,
        }
        video_opts.insert(0, (label, meta))

    # ── Audio-only streams ────────────────────────────────────────────────────
    seen_a = set()
    audio_raw = []
    for f in formats:
        if (f.get("vcodec", "none") not in ("none", None, "")):
            continue
        acodec = f.get("acodec", "none")
        if not acodec or acodec == "none":
            continue
        abr = f.get("abr") or f.get("tbr") or 0
        ext = f.get("ext", "?")
        key = (round(abr / 16) * 16, ext)
        if key in seen_a:
            continue
        seen_a.add(key)
        is_native = (ext == "m4a")
        tag   = GREEN("  [Windows native]") if is_native else ""
        abr_s = f"~{abr:.0f}kbps" if abr else "?"
        label = f"{abr_s}  [{ext}/{acodec[:10]}]{tag}"
        meta  = {"format_id": f["format_id"], "abr": abr, "ext": ext, "acodec": acodec}
        audio_raw.append((abr, label, meta))

    audio_raw.sort(key=lambda x: x[0], reverse=True)
    audio_opts = [(lbl, m) for _, lbl, m in audio_raw]

    return video_opts, audio_opts

# ── Format string builders ────────────────────────────────────────────────────
def build_video_fmt(vmeta, ameta):
    """
    Resilient format string with Windows-native fallback chain.
    If the exact user-chosen format is unavailable, falls back to
    h264+aac in mp4 at the same resolution, then anything at that res, then best.
    """
    vid_id = vmeta["format_id"]
    h      = vmeta.get("height") or 720

    if vmeta.get("combined"):
        # Pre-merged stream — no ffmpeg needed
        return f"{vid_id}/best[height<={h}][ext=mp4]/best"

    if ameta:
        aud_id = ameta["format_id"]
        return (
            f"{vid_id}+{aud_id}"
            f"/bestvideo[height<={h}][ext=mp4][vcodec^=avc]+bestaudio[ext=m4a]"
            f"/bestvideo[height<={h}]+bestaudio"
            f"/best[height<={h}]"
            f"/best"
        )
    # Video only (no audio)
    return f"{vid_id}/bestvideo[height<={h}]/best"

def build_audio_fmt(ameta):
    aud_id = ameta["format_id"]
    return f"{aud_id}/bestaudio[ext=m4a]/bestaudio"

# ── Core yt-dlp options ───────────────────────────────────────────────────────
def base_opts(out_dir, title):
    """
    Central options dict shared by all downloads.

    Key settings that fix reported issues:
    - retries / fragment_retries / file_access_retries  →  survive WinError 10054
    - retry_sleep_functions (exponential backoff)        →  don't hammer server
    - http_chunk_size = 10MB                             →  avoids long-lived connections
    - concurrent_fragment_downloads = 1                  →  stable on Windows (less socket pressure)
    - User-Agent header                                  →  looks like real Chrome, not a bot
    - merge_output_format = mp4                          →  always get a playable mp4
    - NO FFmpegVideoConvertor                            →  was causing double processing + size bloat
    - windowsfilenames = True                            →  safe filenames on NTFS
    """
    opts = {
        "outtmpl":           str(Path(out_dir) / f"{title}.%(ext)s"),
        "windowsfilenames":  True,

        # Network resilience (fixes WinError 10054)
        "retries":                       15,
        "fragment_retries":              15,
        "file_access_retries":           5,
        "skip_unavailable_fragments":    False,
        "concurrent_fragment_downloads": 1,
        "http_chunk_size":               10 * 1024 * 1024,   # 10 MB
        "retry_sleep_functions": {
            "http":     lambda n: min(2 ** n, 30),
            "fragment": lambda n: min(2 ** n, 15),
        },

        # Browser-like headers (prevents server-side connection resets)
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },

        # Output
        "merge_output_format": "mp4",
        "keepvideo":           False,

        # Progress + silence
        "progress_hooks": [progress_hook],
        "quiet":          True,
        "no_warnings":    True,

        # Postprocessors — ONLY metadata embedding (no re-encode / no format conversion)
        # FFmpegVideoConvertor was REMOVED — it caused double processing and size bloat
        "postprocessors": [
            {"key": "FFmpegMetadata", "add_chapters": True},
        ],
    }

    if FFMPEG_PATH:
        opts["ffmpeg_location"] = str(Path(FFMPEG_PATH).parent)

    return opts

# ── Info fetching ─────────────────────────────────────────────────────────────
_FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
}

def fetch_info(url):
    opts = {"quiet": True, "no_warnings": True, "http_headers": _FETCH_HEADERS}
    if FFMPEG_PATH:
        opts["ffmpeg_location"] = str(Path(FFMPEG_PATH).parent)
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)

def ensure_formats(entry, parent_url=None):
    """Re-fetch a playlist entry that lacks format info (flat-extract artefact)."""
    if entry.get("formats"):
        return entry
    item_url = entry.get("webpage_url") or entry.get("url") or parent_url
    if not item_url:
        return entry
    try:
        return fetch_info(item_url)
    except Exception:
        return entry

def _safe_title(info):
    raw = info.get("title") or info.get("id") or "video"
    return re.sub(r'[\\/:*?"<>|]', "_", raw)[:200]

# ── Download functions ────────────────────────────────────────────────────────
def download_video(url, vmeta, ameta, out_dir, info):
    global _last_fn, _max_seen
    _last_fn = _max_seen = 0  # reset progress state

    title   = _safe_title(info)
    opts    = base_opts(out_dir, title)
    opts["format"] = build_video_fmt(vmeta, ameta)

    _part_patterns.append(str(Path(out_dir) / f"{title}*.part"))

    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

def download_audio_only(url, ameta, audio_ext, out_dir, info):
    global _last_fn, _max_seen
    _last_fn = _max_seen = 0

    title   = _safe_title(info)
    opts    = base_opts(out_dir, title)
    opts["format"] = build_audio_fmt(ameta)
    opts["postprocessors"] = [{
        "key":              "FFmpegExtractAudio",
        "preferredcodec":   audio_ext,
        "preferredquality": "0",
    }]

    _part_patterns.append(str(Path(out_dir) / f"{title}*.part"))

    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

# ── Interactive session ───────────────────────────────────────────────────────
def run_once():
    """One full interactive download. Returns True to download another."""

    # FIX: always initialise audio_ext so it is in scope regardless of mode chosen
    audio_ext  = "mp3"
    ext_label  = "MP3"
    aud_label  = ""
    ameta      = None
    res_label  = ""
    vmeta      = {}

    print()

    # ffmpeg check
    if not FFMPEG_PATH:
        print(YELLOW(BOLD("  WARNING: ffmpeg not found!")))
        print(YELLOW("  Merging separate video+audio streams requires ffmpeg."))
        print(YELLOW("  Get it at: https://www.gyan.dev/ffmpeg/builds/  (Windows)"))
        print(YELLOW("  Add ffmpeg\\bin to your system PATH, then restart this script."))
        print(YELLOW("  For now, choose the ** pre-merged stream to avoid needing ffmpeg.\n"))

    # URL
    url = ask("Paste video URL  (YouTube, TikTok, Twitter/X, Instagram ...)")
    if not url:
        print(RED("  No URL entered."))
        return False

    # Output folder
    default_dir = str(Path.home() / "Downloads")
    out_dir = ask("Save to folder", default=default_dir) or default_dir
    Path(out_dir).mkdir(parents=True, exist_ok=True)

    # Fetch info
    print(f"\n  {YELLOW('[...')} Fetching video info ...", end="", flush=True)
    try:
        info = fetch_info(url)
    except Exception as e:
        msg = str(e)
        print(f"\n  {RED('ERROR')} {msg[:250]}")
        hints = {
            "sign in":   "This video requires login.",
            "login":     "This video requires login.",
            "private":   "This video is private.",
            "available": "Video may be geo-blocked or deleted.",
            "10054":     "Network connection was reset. Check your internet.",
        }
        for k, v in hints.items():
            if k in msg.lower():
                print(f"  {YELLOW('Hint:')} {v}")
                break
        return True

    print(f"\r  {GREEN('[OK]')} Info fetched.                    ")

    is_playlist = info.get("_type") == "playlist"

    if is_playlist:
        raw_entries   = list(info.get("entries") or [])  # materialise once — never exhaust generator
        title         = info.get("title", "Playlist")
        uploader      = info.get("uploader") or info.get("channel") or "Unknown"
        hr()
        print(f"  {BOLD('Playlist :')} {title}")
        print(f"  {BOLD('Channel  :')} {uploader}")
        print(f"  {BOLD('Videos   :')} {len(raw_entries)}")
        hr()
        probed_first = ensure_formats(raw_entries[0], url) if raw_entries else info
        probe        = probed_first
        entries      = [probed_first] + raw_entries[1:]
    else:
        entries  = [info]
        title    = info.get("title", "Unknown")
        uploader = info.get("uploader") or info.get("channel") or "Unknown"
        duration = info.get("duration")
        if duration:
            h_, m_, s_ = int(duration)//3600, (int(duration)%3600)//60, int(duration)%60
            dur_s = (f"{h_}h " if h_ else "") + f"{m_}m {s_}s"
        else:
            dur_s = "?"
        hr()
        print(f"  {BOLD('Title    :')} {title}")
        print(f"  {BOLD('Channel  :')} {uploader}")
        print(f"  {BOLD('Duration :')} {dur_s}")
        hr()
        probe = info

    # Mode
    print(f"\n  {BOLD('Mode:')}\n")
    _, mode = choose([
        ("Video  (with audio)", "video"),
        ("Audio only",          "audio"),
    ], prompt="Choose mode")

    video_opts, audio_opts = parse_formats(probe)

    if mode == "video":
        if not video_opts:
            print(RED("\n  No video streams found."))
            return True

        print(f"\n  {BOLD('Resolution')} (tip: ** = fastest, no ffmpeg needed):\n")
        res_label, vmeta = choose(video_opts, prompt="Choose resolution")

        if not vmeta.get("combined") and audio_opts:
            print(f"\n  {BOLD('Audio quality:')}\n")
            aud_choices = audio_opts + [("No audio (video-only / muted)", None)]
            aud_label, ameta = choose(aud_choices, prompt="Choose audio quality")
        else:
            ameta     = None
            aud_label = "(bundled in stream)" if vmeta.get("combined") else "(none)"

    else:  # audio-only
        if not audio_opts:
            print(RED("\n  No audio-only streams found. Try Video mode instead."))
            return True

        print(f"\n  {BOLD('Source quality:')}\n")
        aud_label, ameta = choose(audio_opts, prompt="Choose quality")

        print(f"\n  {BOLD('Output format:')}\n")
        ext_label, audio_ext = choose([
            ("MP3   - universal, plays everywhere (lossy)",          "mp3"),
            ("M4A   - AAC audio, best Windows/iTunes compat  [WIN]", "m4a"),
            ("OPUS  - smallest file, best at low bitrates",          "opus"),
            ("WAV   - uncompressed, very large file",                "wav"),
            ("FLAC  - lossless compressed",                          "flac"),
        ], prompt="Choose format")

    # Confirm
    print()
    hr()
    print(f"  {BOLD('Save to  :')} {out_dir}")
    if mode == "video":
        print(f"  {BOLD('Video    :')} {res_label}")
        print(f"  {BOLD('Audio    :')} {aud_label}")
    else:
        print(f"  {BOLD('Quality  :')} {aud_label}")
        print(f"  {BOLD('Format   :')} {ext_label}")
    hr()

    go = ask("Start download? (y/n)", default="y").lower()
    if go not in ("y", "yes", ""):
        print(f"  {YELLOW('Cancelled.')}")
        return True

    # Download loop
    errors = []
    total  = len(entries)

    for i, entry in enumerate(entries, 1):
        if is_playlist and i > 1:
            entry = ensure_formats(entry, url)

        item_url   = entry.get("webpage_url") or entry.get("url") or url
        item_title = entry.get("title") or f"Item {i}"
        print(f"\n{CYAN(BOLD(f'  [{i}/{total}]'))}  {item_title}")

        try:
            if mode == "video":
                download_video(item_url, vmeta, ameta, out_dir, entry)
            else:
                download_audio_only(item_url, ameta, audio_ext, out_dir, entry)
            print(f"\n  {GREEN(BOLD('DONE!'))}")

        except yt_dlp.utils.DownloadError as e:
            msg = str(e)
            print(f"\n  {RED('FAILED:')} {msg[:200]}")
            if "10054" in msg:
                print(f"  {YELLOW('Tip:')} Connection reset. Try again — the retry logic will handle it.")
            elif "ffmpeg" in msg.lower():
                print(f"  {YELLOW('Tip:')} ffmpeg issue. Install from https://www.gyan.dev/ffmpeg/builds/")
                print(f"  {YELLOW('  Or:')} pick the ** pre-merged stream — no ffmpeg needed.")
            errors.append((item_title, msg[:120]))

        except Exception as e:
            print(f"\n  {RED('ERROR:')} {e}")
            errors.append((item_title, str(e)[:120]))

    # Summary
    print()
    hr()
    ok_count = total - len(errors)
    print(f"  {GREEN(BOLD(f'  {ok_count} / {total} downloaded successfully'))}")
    print(f"  {BOLD('Location :')} {out_dir}")
    if errors:
        print(f"\n  {RED('Failed items:')}")
        for t, e in errors:
            print(f"    - {t}")
            print(f"      {DIM(e)}")
    hr()

    again = ask("\n  Download another? (y/n)", default="n").lower()
    return again in ("y", "yes")

# ── Entry ─────────────────────────────────────────────────────────────────────
def main():
    banner()
    if FFMPEG_PATH:
        print(f"  {GREEN('[OK]')} ffmpeg: {FFMPEG_PATH}")
    else:
        print(f"  {YELLOW('[!]')}  ffmpeg not found  ->  https://www.gyan.dev/ffmpeg/builds/")
    print()

    while True:
        try:
            keep = run_once()
        except KeyboardInterrupt:
            keep = False
        if not keep:
            print(f"\n  {GREEN('Goodbye!')} \n")
            break

if __name__ == "__main__":
    main()
