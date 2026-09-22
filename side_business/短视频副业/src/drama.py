from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Tuple

from PIL import Image, ImageDraw

from src.media import (
    H,
    W,
    audio_duration,
    load_cjk_font,
    synthesize,
    wrap_by_width,
)

# 短剧配色：酒红底，比知识卡更冲
BG_TOP = (18, 8, 12)
BG_BOT = (8, 6, 10)
CRIMSON = (196, 54, 62)
CRIMSON_DIM = (120, 36, 42)
CREAM = (255, 236, 224)
MUTED = (168, 150, 148)
LINE = (62, 36, 40)
WHITE = (255, 250, 246)

ROLE_COLORS = {
    "旁白": {"name": (232, 192, 122), "bar": (232, 192, 122), "avatar": (58, 46, 32)},
    "女主": {"name": (255, 214, 196), "bar": (196, 86, 86), "avatar": (92, 40, 44)},
    "男主": {"name": (186, 214, 240), "bar": (70, 110, 168), "avatar": (32, 48, 78)},
    "男二": {"name": (210, 196, 255), "bar": (110, 86, 168), "avatar": (42, 32, 72)},
    "反派": {"name": (255, 176, 176), "bar": (168, 48, 48), "avatar": (78, 24, 24)},
}


def _gradient_bg() -> Image.Image:
    img = Image.new("RGB", (W, H), BG_BOT)
    draw = ImageDraw.Draw(img)
    steps = 48
    for i in range(steps):
        y0 = int(H * i / steps)
        y1 = int(H * (i + 1) / steps)
        t = i / max(steps - 1, 1)
        color = tuple(int(BG_TOP[j] * (1 - t) + BG_BOT[j] * t) for j in range(3))
        draw.rectangle((0, y0, W, y1), fill=color)
    draw.rectangle((0, 0, 16, H), fill=CRIMSON)
    draw.ellipse((-260, -220, 480, 500), outline=LINE, width=2)
    draw.ellipse((720, 1420, 1320, 2080), outline=LINE, width=2)
    return img


def _fonts(cfg: dict, cover_size: int = 96, body_size: int = 64):
    font_path = cfg["font_path"]
    fallback = cfg["fallback_font_path"]
    title_idx = int(cfg.get("font_index_title", 4))
    body_idx = int(cfg.get("font_index_body", 3))
    return {
        "brand": load_cjk_font(font_path, 30, body_idx, fallback),
        "chip": load_cjk_font(font_path, 28, body_idx, fallback),
        "cover": load_cjk_font(font_path, cover_size, title_idx, fallback),
        "series": load_cjk_font(font_path, 36, body_idx, fallback),
        "name": load_cjk_font(font_path, 44, title_idx, fallback),
        "body": load_cjk_font(font_path, body_size, title_idx, fallback),
        "small": load_cjk_font(font_path, 30, body_idx, fallback),
        "tag": load_cjk_font(font_path, 26, body_idx, fallback),
        "avatar": load_cjk_font(font_path, 52, title_idx, fallback),
    }


def wrap_dialogue(text: str, font, max_width: int, draw: ImageDraw.ImageDraw) -> list:
    import re

    tokens: list = []
    ascii_buf = ""
    for ch in text:
        if ch.isascii() and (ch.isalnum() or ch in ".-+%"):
            ascii_buf += ch
            continue
        if ascii_buf:
            tokens.append(ascii_buf)
            ascii_buf = ""
        tokens.append(ch)
    if ascii_buf:
        tokens.append(ascii_buf)

    def flush_width(chunk: str) -> list:
        lines = []
        current = ""
        for tok in tokens_of(chunk):
            trial = current + tok
            if current and draw.textlength(trial, font=font) > max_width:
                lines.append(current)
                current = tok
            else:
                current = trial
        if current:
            lines.append(current)
        return lines or [chunk]

    def tokens_of(chunk: str) -> list:
        out = []
        buf = ""
        for ch in chunk:
            if ch.isascii() and (ch.isalnum() or ch in ".-+%"):
                buf += ch
            else:
                if buf:
                    out.append(buf)
                    buf = ""
                out.append(ch)
        if buf:
            out.append(buf)
        return out

    parts = [p for p in re.split(r"(?<=[，。！？；、])", text) if p]
    lines: list = []
    current = ""
    for part in parts:
        trial = current + part
        if current and draw.textlength(trial, font=font) > max_width:
            lines.append(current)
            if draw.textlength(part, font=font) > max_width:
                lines.extend(flush_width(part))
                current = ""
            else:
                current = part
        else:
            current = trial
    if current:
        lines.append(current)
    return lines or [text]


def _fit_body(text: str, cfg: dict, draw: ImageDraw.ImageDraw, max_width: int, max_lines: int = 4):
    font_path = cfg["font_path"]
    fallback = cfg["fallback_font_path"]
    title_idx = int(cfg.get("font_index_title", 4))
    for size in (70, 64, 58, 52, 46, 42):
        font = load_cjk_font(font_path, size, title_idx, fallback)
        lines = wrap_dialogue(text, font, max_width, draw)
        if len(lines) <= max_lines:
            return font, lines
    font = load_cjk_font(font_path, 42, title_idx, fallback)
    return font, wrap_dialogue(text, font, max_width, draw)[:max_lines]


def draw_title_frame(item: dict, cfg: dict, dest: Path) -> Path:
    fonts = _fonts(cfg, cover_size=110)
    img = _gradient_bg()
    draw = ImageDraw.Draw(img)

    brand = str(cfg.get("brand", "热门短剧"))
    draw.text((72, 88), brand, font=fonts["brand"], fill=CRIMSON)
    ep = f"第 {int(item.get('episode', 1)):02d} 集"
    ep_w = draw.textlength(ep, font=fonts["brand"])
    draw.text((1008 - ep_w, 88), ep, font=fonts["brand"], fill=CRIMSON)

    draw.line((72, 148, 1008, 148), fill=LINE, width=2)

    series = str(item.get("series", ""))
    draw.text((72, 200), f"《{series}》", font=fonts["series"], fill=MUTED)

    cat = str(item.get("category", "短剧"))
    chip = f"  {cat}  "
    chip_w = int(draw.textlength(chip, font=fonts["chip"])) + 24
    draw.rounded_rectangle((72, 270, 72 + chip_w, 326), radius=8, fill=(48, 18, 22))
    draw.text((84, 280), chip.strip(), font=fonts["chip"], fill=CRIMSON)

    cover = str(item["cover"]).strip()
    cover_font = fonts["cover"]
    lines = wrap_by_width(cover, cover_font, 900, draw)
    if len(lines) > 3:
        lines = lines[:3]
    y = 430
    for line in lines:
        draw.text((72, y), line, font=cover_font, fill=CREAM)
        y += 130

    y += 8
    draw.line((72, y, 340, y), fill=CRIMSON, width=5)
    y += 40
    title = str(item.get("title", "")).strip()
    if title:
        for line in wrap_by_width(title, fonts["small"], 900, draw)[:3]:
            draw.text((72, y), line, font=fonts["small"], fill=MUTED)
            y += 48

    nxt = str(item.get("next", "")).strip()
    if nxt:
        draw.text((72, 1760), nxt, font=fonts["small"], fill=CRIMSON_DIM)

    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, "PNG")
    return dest


def draw_dialogue_frame(item: dict, scene: dict, cfg: dict, dest: Path, index: int, total: int) -> Path:
    fonts = _fonts(cfg)
    img = _gradient_bg()
    draw = ImageDraw.Draw(img)

    speaker = str(scene.get("speaker", "旁白"))
    role = str(scene.get("role") or "旁白")
    palette = ROLE_COLORS.get(role, ROLE_COLORS["旁白"])

    brand = str(cfg.get("brand", "热门短剧"))
    series = str(item.get("series", ""))
    draw.text((72, 88), f"{brand}  ·  {series}", font=fonts["brand"], fill=CRIMSON)
    ep = f"第 {int(item.get('episode', 1)):02d} 集"
    ep_w = draw.textlength(ep, font=fonts["brand"])
    draw.text((1008 - ep_w, 88), ep, font=fonts["brand"], fill=CRIMSON)
    draw.line((72, 148, 1008, 148), fill=LINE, width=2)

    tag = str(scene.get("tag", "")).strip()
    if tag:
        tw = int(draw.textlength(tag, font=fonts["tag"])) + 36
        draw.rounded_rectangle((72, 180, 72 + tw, 232), radius=8, fill=(52, 16, 20))
        draw.rectangle((72, 180, 80, 232), fill=palette["bar"])
        draw.text((90, 190), tag, font=fonts["tag"], fill=palette["name"])

    # 角色头像圈
    cx, cy, r = 540, 430, 78
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=palette["avatar"], outline=palette["bar"], width=4)
    initial = speaker[0]
    iw = draw.textlength(initial, font=fonts["avatar"])
    draw.text((cx - iw / 2, cy - 32), initial, font=fonts["avatar"], fill=palette["name"])

    name_w = draw.textlength(speaker, font=fonts["name"])
    draw.text(((W - name_w) / 2, 540), speaker, font=fonts["name"], fill=palette["name"])
    draw.line(((W - 120) / 2, 610, (W + 120) / 2, 610), fill=palette["bar"], width=3)

    text = str(scene.get("text", "")).strip()
    if role != "旁白":
        text = f"「{text}」"
    body_font, lines = _fit_body(text, cfg, draw, 860, max_lines=5)
    y = 680
    for line in lines:
        lw = draw.textlength(line, font=body_font)
        draw.text(((W - lw) / 2, y), line, font=body_font, fill=CREAM)
        y += int(body_font.size + 18)

    # 进度点
    n = max(total, 1)
    dot_gap = 22
    total_w = n * dot_gap
    x0 = (W - total_w) / 2
    for i in range(n):
        d = 8 if i == index else 6
        fill = CRIMSON if i <= index else LINE
        dx = x0 + i * dot_gap
        draw.ellipse((dx, 1748, dx + d, 1748 + d), fill=fill)

    nxt = str(item.get("next", "")).strip()
    if nxt and index >= total - 1:
        draw.text((72, 1800), nxt, font=fonts["small"], fill=CRIMSON)

    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, "PNG")
    return dest


def make_silence(dest: Path, duration: float, sr: int = 24000) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"anullsrc=r={sr}:cl=mono",
        "-t",
        f"{duration:.3f}",
        "-q:a",
        "9",
        str(dest),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr[-2000:] if proc.stderr else "silence failed")
    return dest


def to_padded_wav(src: Path, dest: Path, pad: float = 0.16, sr: int = 24000) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    af = f"apad=pad_dur={pad:.3f}" if pad > 0 else "anull"
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(src),
        "-ar",
        str(sr),
        "-ac",
        "1",
        "-af",
        af,
        str(dest),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr[-2000:] if proc.stderr else "wav convert failed")
    return dest


def concat_wavs(paths: List[Path], dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as fh:
        for path in paths:
            p = path.resolve().as_posix().replace("'", r"'\''")
            fh.write(f"file '{p}'\n")
        list_path = Path(fh.name)
    try:
        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_path),
            "-c",
            "copy",
            str(dest),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr[-2000:] if proc.stderr else "audio concat failed")
    finally:
        list_path.unlink(missing_ok=True)
    return dest


def render_slideshow(frames: List[Tuple[Path, float]], audio: Path, dest: Path, fps: int = 30) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not frames:
        raise ValueError("没有画面")
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as fh:
        for path, duration in frames:
            p = path.resolve().as_posix().replace("'", r"'\''")
            fh.write(f"file '{p}'\n")
            fh.write(f"duration {max(duration, 0.2):.3f}\n")
        last = frames[-1][0].resolve().as_posix().replace("'", r"'\''")
        fh.write(f"file '{last}'\n")
        list_path = Path(fh.name)
    try:
        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_path),
            "-i",
            str(audio),
            "-vf",
            f"fps={fps},format=yuv420p",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
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
            raise RuntimeError(proc.stderr[-4000:] if proc.stderr else "slideshow failed")
    finally:
        list_path.unlink(missing_ok=True)
    return dest
