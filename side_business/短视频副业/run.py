#!/usr/bin/env python3
"""一键生成短视频：配音、字幕、竖屏成片、发布文案。"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def ensure_venv() -> None:
    venv_dir = ROOT / ".venv"
    venv_python = venv_dir / "bin" / "python3"
    if not venv_python.exists():
        venv_python = venv_dir / "bin" / "python"
    if not venv_python.exists():
        print("正在创建虚拟环境并安装依赖…")
        subprocess.check_call([sys.executable, "-m", "venv", str(venv_dir)])
        venv_python = venv_dir / "bin" / "python3"
        if not venv_python.exists():
            venv_python = venv_dir / "bin" / "python"
        pip = venv_dir / "bin" / "pip"
        subprocess.check_call([str(pip), "install", "--upgrade", "pip"])
        subprocess.check_call([str(pip), "install", "-r", str(ROOT / "requirements.txt")])
    if Path(sys.prefix).resolve() != venv_dir.resolve():
        os.execv(str(venv_python), [str(venv_python), *sys.argv])


def main() -> int:
    os.chdir(ROOT)
    ensure_venv()

    parser = argparse.ArgumentParser(description="短视频副业自动生成")
    parser.add_argument("--id", nargs="+", help="只生成指定文案，如 --id 001 002")
    parser.add_argument("--force", action="store_true", help="覆盖已生成的视频")
    parser.add_argument("--list", action="store_true", help="列出全部文案")
    args = parser.parse_args()

    from src.pipeline import load_config, load_scripts, build_pending
    import asyncio

    cfg = load_config()
    scripts = load_scripts(cfg)

    if args.list:
        for item in scripts:
            series = item.get("series", "")
            ep = item.get("episode", "")
            extra = f"第{ep}集 " if ep != "" else ""
            print(f"{item['id']}  [{item.get('category', '')}] {extra}《{series}》 {item['title']}")
        return 0

    videos = asyncio.run(build_pending(ids=args.id, force=args.force))
    print()
    if videos:
        print(f"新生成 {len(videos)} 条：")
        for path in videos:
            print(f"  {path}")
    else:
        print("没有新视频。用 --force 可强制重做，用 --list 查看文案。")
    print(f"成片目录: {ROOT / cfg['output_dir'] / 'videos'}")
    print(f"发布文案: {ROOT / cfg['output_dir'] / 'captions'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n已中断")
        raise SystemExit(130)
