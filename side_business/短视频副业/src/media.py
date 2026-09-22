from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import List, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1920
BG = (11, 13, 20)
GOLD = (232, 192, 122)
GOLD_DIM = (168, 138, 86)
CREAM = (244, 241, 234)
MUTED = (142, 147, 163)
WHITE = (252, 252, 250)
CHIP_BG = (28, 33, 46)
LINE = (42, 47, 62)


def load_cjk_font(path: str, size: int, index: int, fallback: str) -> ImageFont.FreeTypeFont:
    for idx in (index, 4, 3, 2, 1, 0):
        try:
            return ImageFont.truetype(path, size=size, index=idx)
        except OSError:
            continue
    return ImageFont.truetype(fallback, size=size)


def wrap_by_width(text: str, font: ImageFont.FreeTypeFont, max_width: int, draw: ImageDraw.ImageDraw) -> List[str]:
    text = text.replace("\n", "")
    lines: List[str] = []
    current = ""
    for ch in text:
        trial = current + ch
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = ch
    if current:
        lines.append(current)
    return lines or [text]


def draw_poster(item: dict, cfg: dict, dest: Path) -> Path:
    font_path = cfg["font_path"]
    fallback = cfg["fallback_font_path"]
    title_idx = int(cfg.get("font_index_title", 4))
    body_idx = int(cfg.get("font_index_body", 3))

    font_brand = load_cjk_font(font_path, 36, body_idx, fallback)
    font_chip = load_cjk_font(font_path, 30, body_idx, fallback)
    font_cover = load_cjk_font(font_path, 108, title_idx, fallback)
    font_title = load_cjk_font(font_path, 40, body_idx, fallback)
    font_num = load_cjk_font(font_path, 32, title_idx, fallback)

    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    draw.rectangle((0, 0, 14, H), fill=GOLD)

    draw.ellipse((-220, -180, 420, 460), outline=LINE, width=2)
    draw.ellipse((760, 1480, 1280, 2100), outline=LINE, width=2)
    draw.rectangle((64, 0, 65, H), fill=LINE)

    brand = str(cfg.get("brand", "清醒切片"))
    series = str(cfg.get("series", "认知切片"))
    draw.text((72, 88), f"{brand}  ·  {series}", font=font_brand, fill=GOLD)
    ep = f"第 {item['id']} 期"
    ep_w = draw.textlength(ep, font=font_num)
    draw.text((1008 - ep_w, 90), ep, font=font_num, fill=GOLD)

    draw.line((72, 156, 1008, 156), fill=LINE, width=2)
    draw.line((72, 156, 280, 156), fill=GOLD, width=3)

    category = str(item.get("category", "认知"))
    chip_text = f"  {category}  "
    chip_w = int(draw.textlength(chip_text, font=font_chip)) + 28
    chip_h = 56
    chip_x, chip_y = 72, 196
    draw.rounded_rectangle((chip_x, chip_y, chip_x + chip_w, chip_y + chip_h), radius=8, fill=CHIP_BG)
    draw.text((chip_x + 14, chip_y + 10), chip_text.strip(), font=font_chip, fill=GOLD)

    cover = str(item["cover"]).strip()
    cover_lines = wrap_by_width(cover, font_cover, 900, draw)
    if len(cover_lines) > 3:
        cover_lines = cover_lines[:3]

    y = 320
    for line in cover_lines:
        draw.text((72, y), line, font=font_cover, fill=CREAM)
        y += 128

    y += 12
    draw.line((72, y, 360, y), fill=GOLD, width=4)
    y += 36

    full_title = str(item.get("title", "")).strip()
    if full_title and full_title != cover:
        for line in wrap_by_width(full_title, font_title, 900, draw)[:3]:
            draw.text((72, y), line, font=font_title, fill=MUTED)
            y += 56

    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, "PNG")
    return dest


def _ass_time(seconds: float) -> str:
    cs = max(0, int(round(seconds * 100)))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _clean_script(text: str) -> str:
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    return "".join(lines)


async def synthesize(text: str, voice: str, rate: str, pitch: str, dest: Path) -> List[dict]:
    import edge_tts

    dest.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for attempt in range(1, 6):
        words: List[dict] = []
        audio = bytearray()
        try:
            communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
            async for chunk in communicate.stream():
                kind = chunk.get("type")
                if kind == "audio":
                    audio.extend(chunk["data"])
                elif kind == "WordBoundary":
                    start = chunk["offset"] / 10_000_000
                    end = start + chunk["duration"] / 10_000_000
                    token = str(chunk.get("text", "")).strip()
                    if token:
                        words.append({"text": token, "start": start, "end": end})
            if not audio:
                raise RuntimeError("配音返回空音频")
            dest.write_bytes(bytes(audio))
            return words
        except Exception as exc:
            last_error = exc
            wait = 1.5 * attempt
            print(f"  配音失败，{wait:.1f}s 后重试（{attempt}/5）: {exc}")
            await asyncio.sleep(wait)
    raise RuntimeError(f"配音失败: {last_error}")


def words_to_cues(words: Sequence[dict], max_chars: int = 12) -> List[Tuple[float, float, str]]:
    if not words:
        return []
    cues: List[Tuple[float, float, str]] = []
    buf: List[dict] = []
    punct = set("，。！？；、…,.!?")

    def flush() -> None:
        if not buf:
            return
        text = "".join(w["text"] for w in buf).strip()
        text = re.sub(r"\s+", "", text)
        if text:
            cues.append((buf[0]["start"], buf[-1]["end"], text))
        buf.clear()

    for w in words:
        token = w["text"]
        if buf:
            trial_len = sum(len(x["text"]) for x in buf) + len(token)
            hit_punct = token in punct or token[-1:] in punct
            if trial_len > max_chars or hit_punct:
                if hit_punct and trial_len <= max_chars + 2:
                    buf.append(w)
                    flush()
                    continue
                flush()
        buf.append(w)
        if token in punct:
            flush()
    flush()

    merged: List[Tuple[float, float, str]] = []
    for start, end, text in cues:
        text = text.strip("，、；")
        if not text:
            continue
        if merged and len(text) <= 4:
            ps, _, pt = merged[-1]
            merged[-1] = (ps, end, pt + text)
        else:
            merged.append((start, end, text))
    return merged


def fallback_cues(text: str, duration: float, max_chars: int = 12) -> List[Tuple[float, float, str]]:
    parts = [p.strip() for p in re.split(r"(?<=[，。！？；])", text) if p.strip()]
    chunks: List[str] = []
    for part in parts:
        if len(part) <= max_chars:
            chunks.append(part)
            continue
        for i in range(0, len(part), max_chars):
            chunks.append(part[i : i + max_chars])
    if not chunks:
        chunks = [text]
    total_chars = sum(len(c) for c in chunks) or 1
    cues = []
    t = 0.0
    for c in chunks:
        d = duration * (len(c) / total_chars)
        cues.append((t, t + d, c.strip("，、；")))
        t += d
    return cues


def write_ass(cues: Sequence[Tuple[float, float, str]], dest: Path, font_name: str = "PingFang SC") -> Path:
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},68,&H00F4F1EA,&H000000FF,&H00100E0B,&H64000000,-1,0,0,0,100,100,0,0,1,5,0,2,70,70,380,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for start, end, text in cues:
        if end <= start:
            end = start + 0.35
        safe = text.replace("{", "").replace("}", "").replace("\n", r"\N")
        lines.append(
            f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Default,,0,0,0,,{safe}\n"
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("".join(lines), encoding="utf-8-sig")
    return dest


def audio_duration(path: Path) -> float:
    import json
    import subprocess

    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    data = json.loads(probe.stdout)
    return float(data["format"]["duration"])


def escape_subtitles_path(path: Path) -> str:
    text = path.resolve().as_posix()
    text = text.replace("\\", "\\\\").replace(":", "\\:").replace("'", r"\'")
    return text


def render_video(poster: Path, audio: Path, ass: Path, dest: Path, fps: int = 30) -> Path:
    import subprocess

    dest.parent.mkdir(parents=True, exist_ok=True)
    fontsdir = "/System/Library/Fonts"
    vf = f"subtitles='{escape_subtitles_path(ass)}':fontsdir={fontsdir}"
    cmd = [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-i",
        str(poster),
        "-i",
        str(audio),
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-tune",
        "stillimage",
        "-pix_fmt",
        "yuv420p",
        "-r",
        str(fps),
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        "-movflags",
        "+faststart",
        str(dest),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr[-4000:] if proc.stderr else "ffmpeg failed")
    return dest


def write_caption(item: dict, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    body = str(item.get("publish", "")).strip()
    dest.write_text(body + "\n", encoding="utf-8")
    return dest
