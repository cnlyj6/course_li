#!/usr/bin/env python3
"""Render a tourist-attraction network graph from data.json."""

from __future__ import annotations

import json
import math
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from matplotlib.patches import Circle, FancyBboxPatch

ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT / "data.json"
OUTPUT_PATH = ROOT / "graph.png"
FONT_PATH = "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"

BG = "#f6efe4"
INK = "#2c241b"
LINE = "#8a6a45"
NODE_FILL = "#fff8ee"
NODE_EDGE = "#3d6b4f"
ACCENT = "#c45c26"
LABEL_BG = "#fffdf8"


def load_data() -> dict:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def layout(n: int) -> list[tuple[float, float]]:
    if n == 1:
        return [(0.0, 0.0)]
    if n == 2:
        return [(-1.15, 0.08), (1.15, -0.08)]
    radius = 1.35
    return [
        (radius * math.cos(2 * math.pi * i / n - math.pi / 2),
         radius * math.sin(2 * math.pi * i / n - math.pi / 2))
        for i in range(n)
    ]


def main() -> None:
    data = load_data()
    nodes = data["nodes"]
    edges = data["edges"]
    positions = dict(zip((n["id"] for n in nodes), layout(len(nodes))))

    title_font = FontProperties(fname=FONT_PATH, size=20)
    name_font = FontProperties(fname=FONT_PATH, size=13)
    edge_font = FontProperties(fname=FONT_PATH, size=10)
    meta_font = FontProperties(fname=FONT_PATH, size=9)

    fig, ax = plt.subplots(figsize=(10.5, 6.4), dpi=160)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    ax.set_aspect("equal")
    ax.axis("off")

    ax.set_xlim(-2.35, 2.35)
    ax.set_ylim(-1.55, 1.75)

    ax.text(
        0,
        1.48,
        data.get("title", "旅游景点网状图"),
        ha="center",
        va="center",
        color=INK,
        fontproperties=title_font,
    )
    ax.text(
        0,
        1.22,
        f"{len(nodes)} 个景点  ·  {len(edges)} 条路线",
        ha="center",
        va="center",
        color="#6b5a48",
        fontproperties=meta_font,
    )

    for edge in edges:
        x1, y1 = positions[edge["from"]]
        x2, y2 = positions[edge["to"]]
        ax.plot(
            [x1, x2],
            [y1, y2],
            color=LINE,
            linewidth=2.4,
            solid_capstyle="round",
            zorder=1,
        )
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        label = f"{edge['distance_km']} km\n{edge['mode']} {edge['walk_minutes']} 分钟"
        ax.add_patch(
            FancyBboxPatch(
                (mx - 0.42, my + 0.08),
                0.84,
                0.42,
                boxstyle="round,pad=0.04,rounding_size=0.08",
                facecolor=LABEL_BG,
                edgecolor=LINE,
                linewidth=1.0,
                zorder=2,
            )
        )
        ax.text(
            mx,
            my + 0.29,
            label,
            ha="center",
            va="center",
            color=ACCENT,
            fontproperties=edge_font,
            zorder=3,
            linespacing=1.35,
        )

    radius = 0.38
    for node, (x, y) in zip(nodes, (positions[n["id"]] for n in nodes)):
        ax.add_patch(
            Circle(
                (x, y),
                radius + 0.045,
                facecolor="#e7d3b0",
                edgecolor="none",
                zorder=3,
            )
        )
        ax.add_patch(
            Circle(
                (x, y),
                radius,
                facecolor=NODE_FILL,
                edgecolor=NODE_EDGE,
                linewidth=2.4,
                zorder=4,
            )
        )
        ax.text(
            x,
            y,
            node["name"],
            ha="center",
            va="center",
            color=INK,
            fontproperties=name_font,
            zorder=5,
        )

    fig.tight_layout()
    fig.savefig(OUTPUT_PATH, facecolor=BG, bbox_inches="tight", pad_inches=0.28)
    plt.close(fig)
    print(f"wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
