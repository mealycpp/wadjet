#!/usr/bin/env python3
"""
Draws the charts shown in the README and in docs/RESULTS.md.

  chart_mixing    read from model/RESULTS.txt (output of model/mix_model.py)
  chart_hardware  numbers from the paper (hardware tests on a Zynq-7020)
  chart_cost      numbers from the paper (compiled driver, medians)

Each chart is written twice, for light and for dark pages.

Usage:  python make_charts.py        (needs matplotlib)
"""
import os
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "figures")
RESULTS = os.path.join(HERE, "..", "model", "RESULTS.txt")

THEMES = {
    "light": dict(surface="#ffffff", text="#0b0b0b", muted="#52514e",
                  grid="#e4e3df", a="#2a78d6", b="#eb6834"),
    "dark": dict(surface="#0d1117", text="#f0efec", muted="#c3c2b7",
                 grid="#30363d", a="#3987e5", b="#d95926"),
}

have = {f.name for f in font_manager.fontManager.ttflist}
plt.rcParams["font.family"] = "Inter" if "Inter" in have else "DejaVu Sans"
plt.rcParams["font.size"] = 10


def frame(t, width, height, title, subtitle):
    fig, ax = plt.subplots(figsize=(width, height), dpi=200)
    fig.patch.set_facecolor(t["surface"])
    ax.set_facecolor(t["surface"])
    for side in ("top", "right", "left", "bottom"):
        ax.spines[side].set_visible(False)
    ax.tick_params(axis="both", length=0, colors=t["muted"], labelsize=9)
    ax.xaxis.grid(True, color=t["grid"], linewidth=0.8)
    ax.set_axisbelow(True)
    fig.text(0.02, 0.965, title, color=t["text"], fontsize=12.5,
             fontweight="bold", va="top", ha="left")
    fig.text(0.02, 0.965 - 0.36 / height, subtitle, color=t["muted"],
             fontsize=9.5, va="top", ha="left")
    return fig, ax


def legend(fig, t, items, height):
    x = 0.02
    y = 0.965 - 0.72 / height
    for color, label in items:
        fig.patches.append(plt.Rectangle((x, y - 0.012), 0.014, 0.014 * 7.2 / height / 1.6,
                                         transform=fig.transFigure, color=color))
        fig.text(x + 0.02, y, label, color=t["muted"], fontsize=9, va="center")
        x += 0.03 + 0.0088 * len(label)


def save(fig, name, mode):
    path = os.path.join(OUT, f"{name}_{mode}.png")
    fig.savefig(path, facecolor=fig.get_facecolor())
    plt.close(fig)
    print("wrote", os.path.relpath(path, HERE))


def read_mixing():
    """Rows of the MIX table in model/RESULTS.txt: (rule, attempts, reached, unapproved)."""
    rows, inside = [], False
    with open(RESULTS) as f:
        for line in f:
            if line.startswith("MIX:"):
                inside = True
            elif line.startswith("CUT SHORT"):
                inside = False
            elif inside:
                m = re.match(r"(.+?)\s+(\d+)\s+(\d+)\s+(\d+)\s*$", line)
                if m:
                    rows.append((m.group(1).strip(), int(m.group(2)),
                                 int(m.group(3)), int(m.group(4))))
    return rows


def chart_mixing(mode):
    t = THEMES[mode]
    rows = read_mixing()
    names = {"each write: tag only": "Check each write:\ntag only",
             "each write: tag, forward-only counter": "Check each write:\ntag, forward-only counter",
             "each write: tag, consecutive counter": "Check each write:\ntag, consecutive counter",
             "whole job (WADJET rule)": "Whole job\n(the gate's rule)"}
    attempts = rows[0][1]
    h = 4.4
    fig, ax = frame(t, 7.2, h,
                    "A check on each write lets mixed jobs through",
                    f"{attempts:,} attempts per rule: first writes of one approved job, the rest from another")
    legend(fig, t, [(t["a"], "any write reached the registers"),
                    (t["b"], "accelerator ran an unapproved job")], h)
    bar = 0.3
    for i, (rule, _, reached, unapproved) in enumerate(rows):
        y = len(rows) - 1 - i
        for dy, value, color in ((bar / 2 + 0.02, reached, t["a"]),
                                 (-bar / 2 - 0.02, unapproved, t["b"])):
            ax.barh(y + dy, value, height=bar, color=color)
            ax.text(value + attempts * 0.012, y + dy, f"{value:,}",
                    va="center", ha="left", color=t["text"], fontsize=9)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([names.get(r[0], r[0]) for r in reversed(rows)], color=t["text"])
    ax.set_xlim(0, attempts * 1.12)
    ax.set_xticks([0, 2000, 4000, 6000, 8000, 10000])
    ax.set_xticklabels(["0", "2,000", "4,000", "6,000", "8,000", "10,000"])
    ax.set_ylim(-0.6, len(rows) - 0.4)
    ax.set_xlabel("attempts", color=t["muted"], fontsize=9)
    fig.subplots_adjust(left=0.30, right=0.97, top=0.74, bottom=0.12)
    save(fig, "chart_mixing", mode)


def chart_hardware(mode):
    t = THEMES[mode]
    groups = [("Approved jobs", 21000, 21000),
              ("Altered jobs\n(6 kinds of change)", 12600, 0),
              ("Repeated jobs", 2100, 0)]
    h = 3.7
    fig, ax = frame(t, 7.2, h,
                    "On the board: every approved job released, no other",
                    "Zynq-7020, verdict read from the gate's status register on every attempt")
    legend(fig, t, [(t["a"], "submitted to the gate"), (t["b"], "released to the accelerator")], h)
    bar = 0.3
    for i, (_, sent, released) in enumerate(groups):
        y = len(groups) - 1 - i
        for dy, value, color in ((bar / 2 + 0.02, sent, t["a"]),
                                 (-bar / 2 - 0.02, released, t["b"])):
            ax.barh(y + dy, value, height=bar, color=color)
            ax.text(value + 21000 * 0.012, y + dy, f"{value:,}",
                    va="center", ha="left", color=t["text"], fontsize=9)
    ax.set_yticks(range(len(groups)))
    ax.set_yticklabels([g[0] for g in reversed(groups)], color=t["text"])
    ax.set_xlim(0, 21000 * 1.12)
    ax.set_xticks([0, 5000, 10000, 15000, 20000])
    ax.set_xticklabels(["0", "5,000", "10,000", "15,000", "20,000"])
    ax.set_ylim(-0.6, len(groups) - 0.4)
    ax.set_xlabel("jobs", color=t["muted"], fontsize=9)
    fig.subplots_adjust(left=0.26, right=0.97, top=0.70, bottom=0.14)
    save(fig, "chart_hardware", mode)


def chart_cost(mode):
    t = THEMES[mode]
    h = 3.0
    fig, ax = frame(t, 7.2, h,
                    "A sealed job adds about ten microseconds to a start",
                    "Compiled driver on one board, medians; each figure includes about 1 µs for reading the clock")
    legend(fig, t, [(t["a"], "processor writes registers"),
                    (t["b"], "gate decrypts, checks and issues the writes")], h)
    bar = 0.34
    gap = 0.08
    ax.barh(1, 3.1, height=bar, color=t["a"])
    ax.text(3.1 + 0.2, 1, "3.1 µs  (12 writes)", va="center", color=t["text"], fontsize=9)
    ax.barh(0, 9.4, height=bar, color=t["a"])
    ax.barh(0, 3.6 - gap, left=9.4 + gap, height=bar, color=t["b"])
    ax.text(9.4 / 2, 0, "9.4", va="center", ha="center", color="#ffffff", fontsize=9, fontweight="bold")
    ax.text(9.4 + 1.8, 0, "3.6", va="center", ha="center", color="#ffffff", fontsize=9, fontweight="bold")
    ax.text(13.0 + 0.2, 0, "13.0 µs  (50 staging writes + gate)", va="center", color=t["text"], fontsize=9)
    ax.set_yticks([0, 1])
    ax.set_yticklabels(["Sealed job\nthrough the gate", "Direct start\n(unprotected)"], color=t["text"])
    ax.set_xlim(0, 21)
    ax.set_xticks([0, 5, 10, 15, 20])
    ax.set_ylim(-0.55, 1.55)
    ax.set_xlabel("microseconds", color=t["muted"], fontsize=9)
    fig.subplots_adjust(left=0.22, right=0.97, top=0.64, bottom=0.18)
    save(fig, "chart_cost", mode)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for mode in THEMES:
        chart_mixing(mode)
        chart_hardware(mode)
        chart_cost(mode)
