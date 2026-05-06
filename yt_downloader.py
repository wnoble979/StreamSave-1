#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════╗
║           YouTube Downloader  —  powered by yt-dlp  ║
╚══════════════════════════════════════════════════════╝
Features:
  • List & choose video resolution (4K → 144p)
  • List & choose audio quality / format
  • Audio-only mode (MP3 / M4A / OPUS / WAV)
  • Real-time download progress bar
  • Auto-merge video + audio with ffmpeg
  • Playlist support
"""

import sys
import os
import re
import json
import shutil
import subprocess
from pathlib import Path

# ── dependency check ────────────────────────────────────────────────────────
try:
    import yt_dlp
except ImportError:
    print("yt-dlp not found. Installing …")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "yt-dlp", "-q"])
    import yt_dlp

# ── colours (graceful fallback on Windows without ANSI) ─────────────────────
USE_COLOR = sys.stdout.isatty() and os.name != "nt"

def c(text, code):
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text

CYAN   = lambda t: c(t, "96")
GREEN  = lambda t: c(t, "92")
YELLOW = lambda t: c(t, "93")
RED    = lambda t: c(t, "91")
BOLD   = lambda t: c(t, "1")
DIM    = lambda t: c(t, "2")

# ── helpers ──────────────────────────────────────────────────────────────────
DIVIDER = DIM("─" * 58)

def banner():
    print()
    print(CYAN(BOLD("╔══════════════════════════════════════════════════════╗")))
    print(CYAN(BOLD("║         🎬  YouTube Downloader  (yt-dlp)             ║")))
    print(CYAN(BOLD("╚══════════════════════════════════════════════════════╝")))
    print()

def ask(prompt, default=None):
    hint = f" [{default}]" if default is not None else ""
    try:
        raw = input(f"{BOLD('▶')} {prompt}{hint}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)
    return raw if raw else (str(default) if default is not None else "")

def choose(options, prompt="Enter number"):
    """Print a numbered menu and return the chosen item."""
    for i, (label, _) in enumerate(options, 1):
        print(f"  {GREEN(str(i).rjust(2))}.  {label}")
    print()
    while True:
        raw = ask(prompt, default=1)
        try:
            idx = int(raw)
            if 1 <= idx <= len(options):
                return options[idx - 1][1]
        except ValueError:
            pass
        print(RED(f"  Please enter 1–{len(options)}."))

def hr():
    print(DIVIDER)

# ── progress hook ────────────────────────────────────────────────────────────
_last_filename = ""

def progress_hook(d):
    global _last_filename
    status = d.get("status")

    if status == "downloading":
        fname  = Path(d.get("filename", "")).name
        if fname != _last_filename:
            _last_filename = fname
            print(f"\n  {DIM('File:')} {fname}")

        total   = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
        downloaded = d.get("downloaded_bytes", 0)
        speed   = d.get("speed") or 0
        eta     = d.get("eta") or 0

        pct = (downloaded / total * 100) if total else 0
        bar_len = 30
        filled  = int(bar_len * pct / 100)
        bar     = GREEN("█" * filled) + DIM("░" * (bar_len - filled))

        speed_str = f"{speed/1_048_576:.1f} MB/s" if speed >= 1_048_576 else \
                    f"{speed/1_024:.0f} KB/s" if speed else "? KB/s"
        eta_str   = f"{eta//60}m {eta%60:02d}s" if eta else "--"
        size_str  = f"{downloaded/1_048_576:.1f}/{total/1_048_576:.1f} MB" if total else \
                    f"{downloaded/1_048_576:.1f} MB"

        line = f"  [{bar}] {pct:5.1f}%  {size_str}  {speed_str}  ETA {eta_str}"
        print(f"\r{line}", end="", flush=True)

    elif status == "finished":
        print(f"\n  {GREEN('✔')} Segment downloaded — merging/processing …")

    elif status == "error":
        print(f"\n  {RED('✘')} Error during download.")

# ── fetch video info ─────────────────────────────────────────────────────────
def fetch_info(url):
    opts = {"quiet": True, "no_warnings": True, "extract_flat": False}
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)

# ── format analysis ──────────────────────────────────────────────────────────
def parse_formats(info):
    """Return (video_options, audio_options) as lists of (label, fmt_id) tuples."""
    formats = info.get("formats", [])

    # ── video streams (must carry video) ────────────────────────────────────
    seen_res = set()
    video_opts = []
    for f in reversed(formats):          # best quality last → reversed = best first
        if not f.get("vcodec") or f["vcodec"] == "none":
            continue
        h   = f.get("height") or 0
        fps = f.get("fps") or 0
        tbr = f.get("tbr") or 0
        ext = f.get("ext", "?")
        vcodec = f.get("vcodec", "")[:10]
        key = (h, round(fps))
        if key in seen_res:
            continue
        seen_res.add(key)
        fps_str = f"{fps:.0f}fps" if fps else ""
        label = f"{h}p {fps_str}  [{ext} / {vcodec}]  ~{tbr:.0f} kbps" if tbr \
                else f"{h}p {fps_str}  [{ext} / {vcodec}]"
        video_opts.append((label.strip(), f["format_id"]))

    # best-combined fallback (single-file mp4)
    best_mp4 = next(
        (f for f in reversed(formats)
         if f.get("vcodec", "none") != "none"
         and f.get("acodec", "none") != "none"
         and f.get("ext") == "mp4"),
        None,
    )
    if best_mp4:
        h   = best_mp4.get("height") or "?"
        tbr = best_mp4.get("tbr") or 0
        label = f"{h}p  [mp4 combined — no re-encode needed]  ~{tbr:.0f} kbps"
        video_opts.insert(0, (label, best_mp4["format_id"]))

    # ── audio-only streams ───────────────────────────────────────────────────
    seen_abr = set()
    audio_opts = []
    for f in reversed(formats):
        if f.get("vcodec", "none") != "none":
            continue
        if not f.get("acodec") or f["acodec"] == "none":
            continue
        abr = f.get("abr") or f.get("tbr") or 0
        ext = f.get("ext", "?")
        acodec = f.get("acodec", "")[:12]
        key = (round(abr / 16) * 16, ext)   # bucket by ~16 kbps
        if key in seen_abr:
            continue
        seen_abr.add(key)
        label = f"~{abr:.0f} kbps  [{ext} / {acodec}]" if abr else f"[{ext} / {acodec}]"
        audio_opts.append((label, f["format_id"]))

    return video_opts or [], audio_opts or []

# ── download ─────────────────────────────────────────────────────────────────
def download_video(url, video_fmt, audio_fmt, out_dir, info):
    title = re.sub(r'[\\/:*?"<>|]', "_", info.get("title", "video"))
    outtmpl = str(Path(out_dir) / f"{title}.%(ext)s")

    fmt_str = f"{video_fmt}+{audio_fmt}" if audio_fmt else video_fmt

    opts = {
        "format": fmt_str,
        "outtmpl": outtmpl,
        "merge_output_format": "mp4",
        "progress_hooks": [progress_hook],
        "quiet": True,
        "no_warnings": True,
        "postprocessors": [{
            "key": "FFmpegVideoConvertor",
            "preferedformat": "mp4",
        }],
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

def download_audio_only(url, audio_fmt, audio_format_out, out_dir, info):
    title = re.sub(r'[\\/:*?"<>|]', "_", info.get("title", "audio"))
    outtmpl = str(Path(out_dir) / f"{title}.%(ext)s")

    opts = {
        "format": audio_fmt,
        "outtmpl": outtmpl,
        "progress_hooks": [progress_hook],
        "quiet": True,
        "no_warnings": True,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": audio_format_out,
            "preferredquality": "0",          # best VBR
        }],
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

# ── main flow ─────────────────────────────────────────────────────────────────
def main():
    banner()

    # ── URL ──────────────────────────────────────────────────────────────────
    url = ask("Paste YouTube URL (video or playlist)")
    if not url:
        print(RED("No URL provided. Exiting."))
        sys.exit(1)

    # ── output directory ─────────────────────────────────────────────────────
    default_dir = str(Path.home() / "Downloads")
    out_dir = ask("Save to folder", default=default_dir) or default_dir
    Path(out_dir).mkdir(parents=True, exist_ok=True)

    # ── fetch metadata ────────────────────────────────────────────────────────
    print(f"\n  {YELLOW('⏳')} Fetching video info …", end="", flush=True)
    try:
        info = fetch_info(url)
    except Exception as e:
        print(f"\n  {RED('✘')} Could not fetch info: {e}")
        sys.exit(1)
    print(f"\r  {GREEN('✔')} Info fetched.              ")

    is_playlist = info.get("_type") == "playlist"
    entries     = info.get("entries", [info]) if is_playlist else [info]

    title    = info.get("title", "Unknown")
    uploader = info.get("uploader", "Unknown")
    duration = info.get("duration")
    dur_str  = f"{duration//3600}h {(duration%3600)//60}m {duration%60}s" if duration else "?"
    count    = len(list(entries))

    hr()
    if is_playlist:
        print(f"  {BOLD('Playlist :')} {title}  ({count} videos)")
        print(f"  {BOLD('Channel  :')} {uploader}")
    else:
        print(f"  {BOLD('Title    :')} {title}")
        print(f"  {BOLD('Channel  :')} {uploader}")
        print(f"  {BOLD('Duration :')} {dur_str}")
    hr()

    # ── mode: video or audio-only ─────────────────────────────────────────────
    print(f"\n  {BOLD('Download mode:')}\n")
    mode = choose([
        ("🎬  Video  (with audio)", "video"),
        ("🎵  Audio only",          "audio"),
    ], prompt="Choose mode")

    # ── use the first entry for format probing ────────────────────────────────
    probe = entries[0] if is_playlist else info

    video_opts, audio_opts = parse_formats(probe)

    if mode == "video":
        # ── video resolution ─────────────────────────────────────────────────
        if not video_opts:
            print(RED("  No video formats found. Aborting."))
            sys.exit(1)
        print(f"\n  {BOLD('Available resolutions:')}\n")
        video_fmt = choose(video_opts, prompt="Choose resolution")

        # ── audio quality ─────────────────────────────────────────────────────
        print(f"\n  {BOLD('Audio quality for the video:')}\n")
        audio_choices = audio_opts + [("🔇  No audio (silent video)", "none")]
        audio_fmt_raw = choose(audio_choices, prompt="Choose audio quality")
        audio_fmt = None if audio_fmt_raw == "none" else audio_fmt_raw

    else:  # audio-only
        if not audio_opts:
            print(RED("  No audio formats found. Aborting."))
            sys.exit(1)
        print(f"\n  {BOLD('Source audio quality:')}\n")
        audio_fmt = choose(audio_opts, prompt="Choose quality")

        print(f"\n  {BOLD('Output format:')}\n")
        audio_format_out = choose([
            ("MP3  — universal, lossy",           "mp3"),
            ("M4A  — iTunes / AAC, better quality","m4a"),
            ("OPUS — smallest + best at low kbps","opus"),
            ("WAV  — lossless, large file",        "wav"),
        ], prompt="Choose output format")

    # ── confirm ───────────────────────────────────────────────────────────────
    hr()
    print(f"  {BOLD('Save to :')} {out_dir}")
    if mode == "video":
        print(f"  {BOLD('Video   :')} format_id={video_fmt}")
        print(f"  {BOLD('Audio   :')} format_id={audio_fmt or 'none'}")
    else:
        print(f"  {BOLD('Audio   :')} format_id={audio_fmt} → {audio_format_out.upper()}")
    hr()
    confirm = ask("Start download? (y/n)", default="y").lower()
    if confirm not in ("y", "yes", ""):
        print("  Cancelled.")
        sys.exit(0)

    # ── download (playlist aware) ─────────────────────────────────────────────
    errors = []
    items  = list(entries)
    total  = len(items)

    for i, entry in enumerate(items, 1):
        item_url = entry.get("webpage_url") or entry.get("url") or url
        item_info = entry if not is_playlist else entry

        print(f"\n{CYAN(BOLD(f'[{i}/{total}]'))} {item_info.get('title', item_url)}")

        try:
            if mode == "video":
                download_video(item_url, video_fmt, audio_fmt, out_dir, item_info)
            else:
                download_audio_only(item_url, audio_fmt, audio_format_out, out_dir, item_info)
            print(f"\n  {GREEN(BOLD('✔ Done!'))}")
        except Exception as e:
            print(f"\n  {RED('✘')} Failed: {e}")
            errors.append((item_info.get("title", item_url), str(e)))

    # ── summary ───────────────────────────────────────────────────────────────
    print()
    hr()
    ok = total - len(errors)
    print(f"  {GREEN(BOLD(f'✔ {ok}/{total} downloaded'))} → {out_dir}")
    if errors:
        print(f"\n  {RED('Failed:')}")
        for title, err in errors:
            print(f"    • {title}: {err}")
    hr()
    print()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n  {YELLOW('Interrupted. Goodbye!')}\n")
        sys.exit(0)
