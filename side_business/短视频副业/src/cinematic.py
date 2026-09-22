from __future__ import annotations

import random
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from src import ROOT
from src.media import H, W, load_cjk_font, wrap_by_width

PLATES = ROOT / "assets" / "plates"
FX = ROOT / "assets" / "fx"

SRC_W, SRC_H = 1620, 2880

SPEAKER_KEY = {
    "苏晚": "suwan",
    "陆母": "lumu",
    "林知意": "linzhiyi",
    "陆景深": "lujingshen",
    "顾宴川": "guyan",
    "沈清": "shenqing",
    "陈砚": "chenyan",
    "陈母": "chenmu",
    "陈悦": "chenyue",
    "沈父": "shenfu",
    "宋宁": "songning",
    "顾深": "gushen",
    "周宴": "zhouyan",
}

LOC_WORDS = [
    (("雨", "黑车", "车门", "上车", "伞", "水里"), "rain"),
    (("宴", "主桌", "碗", "婚纱", "宴会", "年会"), "banquet"),
    (("客厅", "回家", "房间", "录取"), "home"),
    (("民政", "领证", "户口"), "civil"),
    (("大厦", "发布会", "大厅", "董事会", "顾氏"), "lobby"),
    (("公章", "总裁办", "股权", "公司"), "office"),
]


def infer_loc(scene: dict, item: dict) -> str:
    if scene.get("loc"):
        return str(scene["loc"])
    blob = f"{scene.get('text', '')}{scene.get('tag', '')}{item.get('cover', '')}{item.get('title', '')}"
    for words, loc in LOC_WORDS:
        if any(word in blob for word in words):
            return loc
    series = str(item.get("series", ""))
    if "闪婚" in series:
        return "civil"
    if "重生" in series:
        return "home"
    return "banquet"


def infer_shot(scene: dict) -> str:
    if scene.get("shot"):
        return str(scene["shot"])
    if scene.get("type") == "title":
        return "title"
    if scene.get("speaker") == "旁白":
        return "wide"
    if scene.get("tag"):
        return "close"
    return "close"


def infer_cam(scene: dict, index: int) -> str:
    if scene.get("cam"):
        return str(scene["cam"])
    shot = infer_shot(scene)
    if scene.get("tag"):
        return "crash_in"
    if shot == "title":
        return "push_in"
    if shot == "wide":
        return "pan_right" if index % 2 == 0 else "pan_left"
    if shot == "close":
        return "push_in" if index % 2 == 0 else "tilt_up"
    return "push_in"


def resolve_plate(scene: dict, item: dict) -> Path:
    if scene.get("plate"):
        named = PLATES / f"{scene['plate']}.png"
        if named.exists():
            return named
    loc = infer_loc(scene, item)
    speaker = str(scene.get("speaker", "旁白"))
    key = SPEAKER_KEY.get(speaker)
    shot = infer_shot(scene)
    candidates: List[str] = []
    if key:
        if key == "guyan" and loc == "rain":
            candidates.append("guyan_car.png")
        candidates.extend(
            [
                f"{key}_{loc}.png",
                f"{key}_banquet.png",
                f"{key}_rain.png",
                f"{key}_car.png",
                f"{key}.png",
            ]
        )
    if speaker == "旁白" or shot in {"wide", "title"}:
        candidates.extend(
            [
                f"{loc}_wide.png",
                "banquet_wide.png",
                "rain_wide.png",
            ]
        )
    if shot == "title":
        cover_key = SPEAKER_KEY.get("苏晚" if "陆家" in str(item.get("series", "")) else "")
        if cover_key:
            candidates.insert(0, f"{cover_key}_banquet.png")
            candidates.insert(1, f"{cover_key}_rain.png")
        if "闪婚" in str(item.get("series", "")):
            candidates.insert(0, "songning.png")
        if "重生" in str(item.get("series", "")):
            candidates.insert(0, "shenqing.png")
    seen = set()
    for name in candidates:
        if name in seen:
            continue
        seen.add(name)
        path = PLATES / name
        if path.exists():
            return path
    wides = [p for p in sorted(PLATES.glob("*_wide.png"))]
    if wides:
        return wides[0]
    found = sorted(PLATES.glob("*.png"))
    if found:
        return found[0]
    raise FileNotFoundError(f"缺少镜头素材，请把人物/场景图放到 {PLATES}")


def _cover(im: Image.Image, w: int, h: int) -> Image.Image:
    im = im.convert("RGB")
    scale = max(w / im.width, h / im.height)
    nw, nh = max(1, int(im.width * scale)), max(1, int(im.height * scale))
    im = im.resize((nw, nh), Image.Resampling.LANCZOS)
    left = (nw - w) // 2
    top = (nh - h) // 2
    return im.crop((left, top, left + w, top + h))


def _vignette(im: Image.Image, strength: float = 0.55) -> Image.Image:
    overlay = Image.new("RGB", im.size, (0, 0, 0))
    mask = Image.new("L", im.size, 0)
    draw = ImageDraw.Draw(mask)
    w, h = im.size
    draw.ellipse((-int(w * 0.15), -int(h * 0.08), int(w * 1.15), int(h * 1.05)), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(radius=120))
    inv = ImageEnhance.Brightness(mask).enhance(0)
    # use inverted vignette as alpha for darkness
    dark = Image.composite(im, overlay, mask)
    return Image.blend(dark, im, 1 - strength)


def _bottom_grade(im: Image.Image) -> Image.Image:
    w, h = im.size
    shade = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(shade)
    band = int(h * 0.32)
    for i in range(band):
        alpha = int(210 * (i / band) ** 1.35)
        y = h - band + i
        draw.line((0, y, w, y), fill=alpha)
    black = Image.new("RGB", (w, h), (0, 0, 0))
    return Image.composite(black, im, shade)


def _fonts(cfg: dict, scale: float = 1.5):
    font_path = cfg["font_path"]
    fallback = cfg["fallback_font_path"]
    title_idx = int(cfg.get("font_index_title", 4))
    body_idx = int(cfg.get("font_index_body", 3))
    s = scale
    return {
        "brand": load_cjk_font(font_path, int(28 * s), body_idx, fallback),
        "ep": load_cjk_font(font_path, int(26 * s), body_idx, fallback),
        "cover": load_cjk_font(font_path, int(72 * s), title_idx, fallback),
        "title": load_cjk_font(font_path, int(32 * s), body_idx, fallback),
        "next": load_cjk_font(font_path, int(26 * s), body_idx, fallback),
    }


def compose_still(item: dict, scene: dict, cfg: dict, dest: Path, index: int) -> Path:
    plate = resolve_plate(scene, item)
    img = _cover(Image.open(plate), SRC_W, SRC_H)
    img = ImageEnhance.Contrast(img).enhance(1.08)
    img = ImageEnhance.Color(img).enhance(0.92)
    img = _vignette(img, 0.42)
    img = _bottom_grade(img)
    draw = ImageDraw.Draw(img)
    fonts = _fonts(cfg)
    cream = (255, 236, 224)
    muted = (168, 150, 148)
    crimson = (196, 54, 62)

    ep = f"第{int(item.get('episode', 1)):02d}集"
    series = str(item.get("series", ""))
    draw.text((72, 78), f"{series}", font=fonts["brand"], fill=crimson)
    ep_w = draw.textlength(ep, font=fonts["ep"])
    draw.text((SRC_W - 72 - ep_w, 80), ep, font=fonts["ep"], fill=(255, 255, 255, 180))

    if scene.get("type") == "title":
        cover = str(item.get("cover", "")).strip()
        y = SRC_H - 780
        draw.rectangle((72, y - 24, 220, y - 16), fill=crimson)
        lines = wrap_by_width(cover, fonts["cover"], SRC_W - 160, draw)[:2]
        for line in lines:
            draw.text((72, y), line, font=fonts["cover"], fill=cream)
            y += int(fonts["cover"].size + 18)
        subtitle = str(item.get("title", "")).strip()
        if subtitle:
            for line in wrap_by_width(subtitle, fonts["title"], SRC_W - 160, draw)[:2]:
                draw.text((72, y + 12), line, font=fonts["title"], fill=muted)
                y += int(fonts["title"].size + 10)

    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, "PNG", optimize=True)
    return dest


def ensure_rain_texture() -> Path:
    FX.mkdir(parents=True, exist_ok=True)
    path = FX / "rain.png"
    if path.exists():
        return path
    w, h = 1080, 3840
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    rng = random.Random(7)
    for _ in range(1100):
        x = rng.randint(0, w - 1)
        y = rng.randint(0, h - 1)
        length = rng.randint(22, 70)
        alpha = rng.randint(40, 130)
        draw.line((x, y, x + 3, y + length), fill=(214, 226, 255, alpha), width=1)
    img.save(path, "PNG")
    return path


def _camera_chain(motion: str, duration: float, fps: int = 30) -> str:
    frames = max(int(round(float(duration) * fps)), 8)
    last = max(frames - 1, 1)
    prep = f"scale={SRC_W}:{SRC_H}:force_original_aspect_ratio=increase,crop={SRC_W}:{SRC_H}"
    if motion == "crash_in":
        z = f"1+0.28*on/{last}"
        x = "iw/2-(iw/zoom/2)"
        y = "ih*0.32-(ih/zoom)*0.32"
    elif motion == "pull_out":
        z = f"1.22-0.18*on/{last}"
        x = "iw/2-(iw/zoom/2)"
        y = "ih/2-(ih/zoom/2)"
    elif motion == "pan_right":
        z = "1.12"
        x = f"(iw-iw/zoom)*on/{last}"
        y = "ih*0.38-(ih/zoom)*0.38"
    elif motion == "pan_left":
        z = "1.12"
        x = f"(iw-iw/zoom)*(1-on/{last})"
        y = "ih*0.40-(ih/zoom)*0.40"
    elif motion == "tilt_up":
        z = "1.14"
        x = "iw/2-(iw/zoom/2)"
        y = f"(ih-ih/zoom)*(0.62-0.34*on/{last})"
    else:
        z = f"1.02+0.16*on/{last}"
        x = "iw/2-(iw/zoom/2)"
        y = "ih*0.36-(ih/zoom)*0.36"
    zoompan = f"zoompan=z='{z}':x='{x}':y='{y}':d=1:s={W}x{H}:fps={fps}"
    grade = "eq=contrast=1.07:brightness=-0.03:saturation=0.88:gamma=0.97,unsharp=5:5:0.35"
    return f"{prep},{zoompan},{grade}"


def wrap_caption(text: str, width: int = 14) -> str:
    text = text.strip()
    if len(text) <= width:
        return text
    parts: List[str] = []
    buf = ""
    for ch in text:
        buf += ch
        if ch in "，。！？；、 " and len(buf) >= 8:
            parts.append(buf.strip())
            buf = ""
        elif len(buf) >= width:
            parts.append(buf.strip())
            buf = ""
    if buf.strip():
        parts.append(buf.strip())
    return "\\N".join(parts[:3])


def write_shot_ass(speaker: str, text: str, dest: Path, end: float) -> Path:
    end = max(end, 0.35)
    cs = max(1, int(round(end * 100)))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    t1 = f"{h}:{m:02d}:{s:02d}.{cs:02d}"
    body = wrap_caption(text)
    name = "" if speaker in {"旁白", ""} else speaker
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Name,PingFang SC,34,&H003E36C4,&H000000FF,&H00100010,&H64000000,-1,0,0,0,100,100,0,0,1,3,0,2,70,70,210,1
Style: Line,PingFang SC,54,&H00E0ECFF,&H000000FF,&H00100010,&H80000000,-1,0,0,0,100,100,0,0,1,5,0,2,64,64,84,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    if name:
        lines.append(f"Dialogue: 0,0:00:00.00,{t1},Name,,0,0,0,,{name}\n")
    if body:
        safe = body.replace("{", "").replace("}", "")
        lines.append(f"Dialogue: 0,0:00:00.00,{t1},Line,,0,0,0,,{safe}\n")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("".join(lines), encoding="utf-8-sig")
    return dest


def render_shot(
    still: Path,
    audio: Path,
    dest: Path,
    duration: float,
    motion: str,
    ass: Optional[Path] = None,
    rain: bool = False,
    fps: int = 30,
) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    chain = _camera_chain(motion, duration, fps)
    filters = ["[0:v]" + chain + "[base]"]
    current = "base"
    inputs = ["-loop", "1", "-framerate", str(fps), "-i", str(still), "-i", str(audio)]
    if rain:
        rain_path = ensure_rain_texture()
        inputs.extend(["-loop", "1", "-i", str(rain_path)])
        filters.append(
            f"[2:v]format=rgba,colorchannelmixer=aa=0.38,scale={W}:{H * 2},crop={W}:{H}:0:'mod(n*8\\,{H})'[rain]"
        )
        filters.append(f"[{current}][rain]overlay[wet]")
        current = "wet"
    if ass and ass.exists():
        try:
            ass_arg = ass.resolve().relative_to(ROOT.resolve()).as_posix()
        except ValueError:
            ass_arg = ass.resolve().as_posix().replace("\\", "\\\\").replace(":", "\\:")
        ass_arg = ass_arg.replace("'", r"\'")
        filters.append(
            f"[{current}]subtitles='{ass_arg}':fontsdir=/System/Library/Fonts,format=yuv420p[v]"
        )
        current = "v"
    else:
        filters.append(f"[{current}]format=yuv420p[v]")
        current = "v"
    cmd = [
        "ffmpeg",
        "-y",
        *inputs,
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[v]",
        "-map",
        "1:a",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-r",
        str(fps),
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-t",
        f"{duration:.3f}",
        "-shortest",
        "-movflags",
        "+faststart",
        str(dest),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr[-4000:] if proc.stderr else "shot render failed")
    return dest


def concat_clips(clips: List[Path], dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not clips:
        raise ValueError("没有镜头")
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as fh:
        for path in clips:
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
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(dest),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr[-4000:] if proc.stderr else "concat failed")
    finally:
        list_path.unlink(missing_ok=True)
    return dest
