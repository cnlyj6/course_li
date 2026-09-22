from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

from src import ROOT
from src.drama import (
    concat_wavs,
    draw_dialogue_frame,
    draw_title_frame,
    make_silence,
    render_slideshow,
    to_padded_wav,
)
from src.media import (
    _clean_script,
    audio_duration,
    draw_poster,
    fallback_cues,
    render_video,
    synthesize,
    words_to_cues,
    write_ass,
    write_caption,
)


def load_bundle(cfg: dict) -> Tuple[List[dict], dict]:
    path = ROOT / cfg["content_file"]
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    videos = data.get("videos") or []
    if not videos:
        raise ValueError(f"{path} 里没有 videos")
    return videos, data.get("cast") or {}


def load_config() -> dict:
    path = ROOT / "config.yaml"
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_scripts(cfg: dict) -> List[dict]:
    videos, _ = load_bundle(cfg)
    return videos


def state_path(cfg: dict) -> Path:
    return ROOT / cfg["output_dir"] / "state.json"


def load_state(cfg: dict) -> dict:
    path = state_path(cfg)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(cfg: dict, state: dict) -> None:
    path = state_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def slug_name(item: dict) -> str:
    cover = str(item["cover"]).replace(" ", "").replace("/", "")
    return f"{item['id']}_{cover}"


def output_dirs(cfg: dict) -> Dict[str, Path]:
    base = ROOT / cfg["output_dir"]
    dirs = {
        "base": base,
        "videos": base / "videos",
        "audio": base / "audio",
        "posters": base / "posters",
        "subs": base / "subs",
        "captions": base / "captions",
        "work": base / "work",
    }
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    return dirs


async def build_talking_head(item: dict, cfg: dict) -> Path:
    dirs = output_dirs(cfg)
    name = slug_name(item)
    poster = dirs["posters"] / f"{name}.png"
    audio = dirs["audio"] / f"{item['id']}.mp3"
    ass = dirs["subs"] / f"{item['id']}.ass"
    caption = dirs["captions"] / f"{item['id']}.txt"
    video = dirs["videos"] / f"{name}.mp4"

    script = _clean_script(item["script"])
    draw_poster(item, cfg, poster)
    write_caption(item, caption)

    words = await synthesize(
        script,
        voice=cfg["voice"],
        rate=str(cfg.get("rate", "+0%")),
        pitch=str(cfg.get("pitch", "+0Hz")),
        dest=audio,
    )
    duration = audio_duration(audio)
    cues = words_to_cues(words)
    if not cues:
        cues = fallback_cues(script, duration)
    write_ass(cues, ass)
    render_video(poster, audio, ass, video, fps=int(cfg.get("fps", 30)))
    return video


async def build_drama(item: dict, cfg: dict, cast: dict) -> Path:
    dirs = output_dirs(cfg)
    name = slug_name(item)
    work = dirs["work"] / str(item["id"])
    frames_dir = work / "frames"
    audio_dir = work / "audio"
    wav_dir = work / "wav"
    caption = dirs["captions"] / f"{item['id']}.txt"
    video = dirs["videos"] / f"{name}.mp4"
    write_caption(item, caption)

    scenes = item.get("scenes") or []
    if not scenes:
        raise ValueError(f"{item['id']} 没有 scenes")

    frames: List[Tuple[Path, float]] = []
    wavs: List[Path] = []
    total = len(scenes)

    for i, raw in enumerate(scenes):
        scene = dict(raw)
        speaker = str(scene.get("speaker", "旁白"))
        info = cast.get(speaker) or {}
        scene["role"] = info.get("role") or ("旁白" if speaker == "旁白" else "女主")
        frame_path = frames_dir / f"{i:03d}.png"
        raw_audio = audio_dir / f"{i:03d}.mp3"
        wav_path = wav_dir / f"{i:03d}.wav"

        if scene.get("type") == "title":
            draw_title_frame(item, cfg, frame_path)
            duration = float(scene.get("duration", 2.0))
            make_silence(raw_audio, duration)
            to_padded_wav(raw_audio, wav_path, pad=0.0)
            actual = audio_duration(wav_path)
            frames.append((frame_path, actual))
            wavs.append(wav_path)
            print(f"    片头 {i + 1}/{total}")
            continue

        draw_dialogue_frame(item, scene, cfg, frame_path, i, total)
        voice = str(info.get("voice") or cfg["voice"])
        rate = str(info.get("rate") or cfg.get("rate", "+0%"))
        pitch = str(info.get("pitch") or cfg.get("pitch", "+0Hz"))
        text = str(scene.get("text", "")).strip()
        print(f"    配音 {i + 1}/{total} {speaker}")
        await synthesize(text, voice=voice, rate=rate, pitch=pitch, dest=raw_audio)
        pad = 0.2 if i < total - 1 else 0.08
        to_padded_wav(raw_audio, wav_path, pad=pad)
        actual = audio_duration(wav_path)
        frames.append((frame_path, actual))
        wavs.append(wav_path)
        await asyncio.sleep(0.8)

    mixed = audio_dir / "full.wav"
    concat_wavs(wavs, mixed)
    render_slideshow(frames, mixed, video, fps=int(cfg.get("fps", 30)))
    return video


async def build_one(item: dict, cfg: dict, cast: dict) -> Path:
    if item.get("scenes"):
        return await build_drama(item, cfg, cast)
    return await build_talking_head(item, cfg)


async def build_pending(ids: Optional[List[str]] = None, force: bool = False) -> List[Path]:
    cfg = load_config()
    scripts, cast = load_bundle(cfg)
    state = load_state(cfg)
    done: List[Path] = []

    selected = scripts
    if ids:
        wanted = set(ids)
        selected = [item for item in scripts if str(item["id"]) in wanted]
        missing = wanted - {str(item["id"]) for item in selected}
        if missing:
            raise ValueError(f"找不到文案 id: {', '.join(sorted(missing))}")

    for item in selected:
        vid = str(item["id"])
        prev = state.get(vid) or {}
        if prev.get("status") == "done" and not force:
            video_path = ROOT / prev["video"] if not Path(prev["video"]).is_absolute() else Path(prev["video"])
            if video_path.exists():
                print(f"[跳过] {vid} 已生成: {video_path}")
                continue
        print(f"[生成] {vid} 《{item.get('series', '')}》 {item['cover']}")
        try:
            video = await build_one(item, cfg, cast)
        except Exception as exc:
            state[vid] = {
                "status": "error",
                "error": str(exc),
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            }
            save_state(cfg, state)
            print(f"[失败] {vid}: {exc}")
            continue
        rel = video.relative_to(ROOT)
        state[vid] = {
            "status": "done",
            "video": str(rel),
            "title": item.get("title") or item["cover"],
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        save_state(cfg, state)
        print(f"[完成] {rel}")
        done.append(video)
        await asyncio.sleep(1.0)
    return done
