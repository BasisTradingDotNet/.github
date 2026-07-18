#!/usr/bin/env python3
"""Render the org-profile developer-stats SVGs from data/*.csv.

Every chart is rendered twice (dark/light) with a transparent background so
the profile README can use <picture> + prefers-color-scheme, matching the
existing logo treatment.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
from pathlib import Path

import matplotlib

matplotlib.use("svg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter, MaxNLocator  # noqa: E402

THEMES = {
    "dark": {
        "text": "#e6edf3",
        "muted": "#9198a1",
        "grid": "#30363d",
        "blue": "#58a6ff",
        "green": "#3fb950",
        "red": "#f85149",
        "purple": "#bc8cff",
        "orange": "#f0883e",
        "cyan": "#39c5cf",
        "fill_alpha": 0.22,
    },
    "light": {
        "text": "#1f2328",
        "muted": "#59636e",
        "grid": "#d1d9e0",
        "blue": "#0969da",
        "green": "#1a7f37",
        "red": "#cf222e",
        "purple": "#8250df",
        "orange": "#bc4c00",
        "cyan": "#1b7c83",
        "fill_alpha": 0.15,
    },
}

CAT_COLORS = {"be": "blue", "fe": "orange", "infra": "muted"}
CAT_LABELS = {"be": "Backend", "fe": "Frontend", "infra": "Infra & docs"}

LANG_COLORS = {
    "TypeScript": "#3178c6", "Rust": "#dea584", "Python": "#3572A5",
    "JavaScript": "#f1e05a", "Solidity": "#AA6746", "Shell": "#89e051",
    "CSS": "#663399", "HTML": "#e34c26", "Markdown": "#083fa1",
    "TOML": "#9c4221", "YAML": "#cb171e", "JSON": "#8b949e",
    "SQL": "#e38c00", "Prisma": "#5a67d8", "XML": "#0060ac",
}


def human(n: float, _pos=None) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}k"
    return f"{n:.0f}"


def load_daily(data_dir: Path) -> list[dict]:
    rows = []
    with open(data_dir / "daily.csv") as f:
        for row in csv.DictReader(f):
            rows.append({
                "date": dt.date.fromisoformat(row["date"]),
                **{k: int(v) for k, v in row.items() if k != "date"},
            })
    return rows


def new_fig(theme: dict, width=9.6, height=3.2):
    fig, ax = plt.subplots(figsize=(width, height), dpi=100)
    fig.patch.set_alpha(0)
    ax.set_facecolor("none")
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(theme["grid"])
    ax.tick_params(colors=theme["muted"], labelsize=9)
    ax.yaxis.grid(True, color=theme["grid"], linewidth=0.6, alpha=0.6)
    ax.set_axisbelow(True)
    return fig, ax


def style_dates(ax, theme):
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.MO, interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    for lbl in ax.get_xticklabels():
        lbl.set_color(theme["muted"])


def title(ax, theme, text, subtitle=None):
    ax.set_title(text, color=theme["text"], fontsize=13, fontweight="bold",
                 loc="left", pad=26 if subtitle else 14)
    if subtitle:
        ax.text(0, 1.045, subtitle, transform=ax.transAxes, fontsize=9,
                color=theme["muted"])


def top_legend(ax, theme, ncols):
    leg = ax.legend(loc="lower right", frameon=False, fontsize=9, ncols=ncols,
                    bbox_to_anchor=(1.0, 1.0), borderpad=0, borderaxespad=0.3)
    for txt in leg.get_texts():
        txt.set_color(theme["muted"])


EXT = "svg"


def save(fig, out_dir: Path, name: str, theme_name: str):
    path = out_dir / f"{name}_{theme_name}.{EXT}"
    fig.savefig(path, transparent=True, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    print(f"  {path.name}")


def chart_loc(daily, out_dir, theme_name, t):
    fig, ax = new_fig(t)
    xs = [r["date"] for r in daily]
    ys = [r["loc"] for r in daily]
    ax.fill_between(xs, ys, color=t["blue"], alpha=t["fill_alpha"], linewidth=0)
    ax.plot(xs, ys, color=t["blue"], linewidth=2)
    ax.yaxis.set_major_formatter(FuncFormatter(human))
    ax.set_ylim(bottom=0)
    ax.text(xs[-1], ys[-1], f"  {ys[-1]:,}", color=t["blue"], fontsize=10,
            fontweight="bold", va="center")
    style_dates(ax, t)
    title(ax, t, "Lines of code", "Raw tracked lines across all repos, vendored code excluded · daily")
    save(fig, out_dir, "loc", theme_name)


def chart_churn(daily, out_dir, theme_name, t):
    fig, ax = new_fig(t)
    xs = [r["date"] for r in daily]
    ax.bar(xs, [r["additions"] for r in daily], width=1.0,
           color=t["green"], label="Additions")
    ax.bar(xs, [-r["deletions"] for r in daily], width=1.0,
           color=t["red"], label="Deletions")
    ax.axhline(0, color=t["grid"], linewidth=0.8)
    ax.set_yscale("symlog", linthresh=100)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, p: human(abs(v))))
    style_dates(ax, t)
    top_legend(ax, t, ncols=2)
    title(ax, t, "Line additions & deletions",
          "Per day on default branches (log scale)")
    save(fig, out_dir, "churn", theme_name)


def chart_repos(daily, out_dir, theme_name, t):
    fig, ax = new_fig(t, height=2.6)
    xs = [r["date"] for r in daily]
    ys = [r["repos"] for r in daily]
    ax.fill_between(xs, ys, step="post", color=t["purple"], alpha=t["fill_alpha"])
    ax.step(xs, ys, where="post", color=t["purple"], linewidth=2)
    ax.set_ylim(bottom=0)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True, nbins=5))
    ax.text(xs[-1], ys[-1], f"  {ys[-1]}", color=t["purple"], fontsize=10,
            fontweight="bold", va="center")
    style_dates(ax, t)
    title(ax, t, "Repositories")
    save(fig, out_dir, "repos", theme_name)


def chart_languages(data_dir, out_dir, theme_name, t):
    langs = []
    with open(data_dir / "languages.csv") as f:
        for row in csv.DictReader(f):
            langs.append((row["language"], int(row["lines"])))
    top = [(l, n) for l, n in langs if l not in ("Other", "Text")][:10]
    top.reverse()
    fig, ax = new_fig(t, height=3.6)
    names = [l for l, _ in top]
    vals = [n for _, n in top]
    colors = [LANG_COLORS.get(l, t["muted"]) for l in names]
    bars = ax.barh(names, vals, color=colors, height=0.62)
    ax.xaxis.set_major_formatter(FuncFormatter(human))
    ax.xaxis.grid(True, color=t["grid"], linewidth=0.6, alpha=0.6)
    ax.yaxis.grid(False)
    for bar, v in zip(bars, vals):
        ax.text(bar.get_width() + max(vals) * 0.01, bar.get_y() + bar.get_height() / 2,
                f"{v:,}", va="center", fontsize=9, color=t["text"])
    for lbl in ax.get_yticklabels():
        lbl.set_color(t["text"])
        lbl.set_fontsize(10)
    ax.set_xlim(0, max(vals) * 1.12)
    title(ax, t, "Lines per language", "Current snapshot")
    save(fig, out_dir, "languages", theme_name)


def chart_focus(daily, out_dir, theme_name, t):
    fig, ax = new_fig(t)
    active = [r for r in daily
              if r["fe_changed"] + r["be_changed"] + r["infra_changed"] > 0]
    xs = [r["date"] for r in active]
    bottoms = [0.0] * len(active)
    for cat in ("be", "fe", "infra"):
        shares = []
        for r in active:
            total = r["fe_changed"] + r["be_changed"] + r["infra_changed"]
            shares.append(100.0 * r[f"{cat}_changed"] / total)
        ax.bar(xs, shares, bottom=bottoms, width=1.0,
               color=t[CAT_COLORS[cat]], label=CAT_LABELS[cat])
        bottoms = [b + s for b, s in zip(bottoms, shares)]
    ax.set_ylim(0, 100)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, p: f"{v:.0f}%"))
    style_dates(ax, t)
    top_legend(ax, t, ncols=3)
    title(ax, t, "Focus — backend vs frontend",
          "Share of lines changed per active day")
    save(fig, out_dir, "focus", theme_name)


def chart_punchcard(data_dir, out_dir, theme_name, t):
    grid = {}
    with open(data_dir / "punchcard.csv") as f:
        for row in csv.DictReader(f):
            grid[(int(row["weekday"]), int(row["hour"]))] = int(row["commits"])
    fig, ax = new_fig(t, height=3.0)
    ax.yaxis.grid(False)
    max_n = max(grid.values())
    xs, ys, sizes = [], [], []
    for (wd, hr), n in grid.items():
        xs.append(hr)
        ys.append(wd)
        sizes.append(30 + 500 * (n / max_n))
    ax.scatter(xs, ys, s=sizes, color=t["cyan"], alpha=0.75, linewidths=0)
    ax.set_yticks(range(7))
    ax.set_yticklabels(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
    ax.set_xticks(range(0, 24, 2))
    ax.set_xticklabels([f"{h:02d}" for h in range(0, 24, 2)])
    ax.set_xlim(-0.8, 23.8)
    ax.set_ylim(6.7, -0.7)
    for lbl in ax.get_yticklabels():
        lbl.set_color(t["text"])
    ax.spines["left"].set_visible(False)
    ax.spines["bottom"].set_visible(False)
    ax.tick_params(length=0)
    title(ax, t, "Commit punch card", "All commits by UTC hour and weekday")
    save(fig, out_dir, "punchcard", theme_name)


def chart_prs(data_dir, out_dir, theme_name, t):
    path = data_dir / "prs_weekly.csv"
    if not path.exists():
        return
    weeks, counts = [], []
    with open(path) as f:
        for row in csv.DictReader(f):
            weeks.append(dt.date.fromisoformat(row["week_start"]))
            counts.append(int(row["prs_merged"]))
    fig, ax = new_fig(t, height=2.8)
    ax.bar(weeks, counts, width=5.6, color=t["green"], alpha=0.9)
    for w, c in zip(weeks, counts):
        ax.text(w, c + max(counts) * 0.02, str(c), ha="center", fontsize=8,
                color=t["muted"])
    ax.yaxis.set_major_locator(MaxNLocator(integer=True, nbins=5))
    style_dates(ax, t)
    title(ax, t, "Pull requests merged", "Per week, all repos")
    save(fig, out_dir, "prs", theme_name)


def squarify(sizes, x, y, w, h):
    """Squarified treemap layout (Bruls et al.). `sizes` sorted descending;
    returns one (x, y, w, h) rect per size, tiling the given rectangle."""
    total = sum(sizes)
    areas = [s / total * w * h for s in sizes]
    rects = []

    def worst(row, side):
        s = sum(row)
        if not s or not side:
            return 1e9
        thickness = s / side
        ratios = []
        for a in row:
            length = a / thickness
            ratios.append(max(length / thickness, thickness / length))
        return max(ratios)

    i = 0
    while i < len(areas):
        side = min(w, h)
        row = [areas[i]]
        i += 1
        while i < len(areas) and worst(row + [areas[i]], side) <= worst(row, side):
            row.append(areas[i])
            i += 1
        thickness = sum(row) / side
        if w >= h:  # lay the row vertically along the left edge
            cy = y
            for a in row:
                rh = a / thickness
                rects.append((x, cy, thickness, rh))
                cy += rh
            x += thickness
            w -= thickness
        else:  # lay the row horizontally along the top edge
            cx = x
            for a in row:
                rw = a / thickness
                rects.append((cx, y, rw, thickness))
                cx += rw
            y += thickness
            h -= thickness
    return rects


def chart_treemap(data_dir, out_dir, theme_name, t):
    sizes = []
    with open(data_dir / "repo_sizes.csv") as f:
        for row in csv.DictReader(f):
            sizes.append(int(row["lines"]))
    sizes = [s for s in sizes if s > 0]
    fig, ax = plt.subplots(figsize=(9.6, 3.4), dpi=100)
    fig.patch.set_alpha(0)
    ax.set_facecolor("none")
    ax.axis("off")
    rects = squarify(sizes, 0, 0, 96, 34)
    palette = [t["blue"], t["purple"], t["cyan"], t["green"], t["orange"]]
    for i, ((rx, ry, rw, rh), s) in enumerate(zip(rects, sizes)):
        color = palette[i % len(palette)]
        ax.add_patch(plt.Rectangle((rx + 0.25, ry + 0.25), rw - 0.5, rh - 0.5,
                                   facecolor=color, alpha=0.55 if theme_name == "dark" else 0.45,
                                   edgecolor="none"))
        if rw > 7 and rh > 4:
            ax.text(rx + rw / 2, ry + rh / 2, human(s), ha="center", va="center",
                    fontsize=min(14, 5 + rw / 3), color=t["text"], fontweight="bold")
    ax.set_xlim(0, 96)
    ax.set_ylim(34, 0)
    ax.set_title("Lines of code by repository (anonymized)", color=t["text"],
                 fontsize=13, fontweight="bold", loc="left", pad=10)
    save(fig, out_dir, "treemap", theme_name)


def chart_summary(daily, data_dir, out_dir, theme_name, t):
    total_loc = daily[-1]["loc"]
    total_commits = sum(r["commits"] for r in daily)
    total_add = sum(r["additions"] for r in daily)
    repos = daily[-1]["repos"]
    prs = 0
    if (data_dir / "prs_weekly.csv").exists():
        with open(data_dir / "prs_weekly.csv") as f:
            prs = sum(int(r["prs_merged"]) for r in csv.DictReader(f))
    # streaks over days with >=1 commit
    longest = cur = 0
    for r in daily:
        cur = cur + 1 if r["commits"] > 0 else 0
        longest = max(longest, cur)
    current = 0
    for r in reversed(daily):
        if r["commits"] > 0:
            current += 1
        else:
            break
    stats = [
        (f"{total_loc:,}", "lines of code"),
        (f"{total_commits:,}", "commits"),
        (f"{prs:,}", "PRs merged"),
        (f"{total_add:,}", "lines added"),
        (f"{repos}", "repositories"),
        (f"{current}d / {longest}d", "streak (now / best)"),
    ]
    fig, ax = plt.subplots(figsize=(9.6, 1.15), dpi=100)
    fig.patch.set_alpha(0)
    ax.axis("off")
    n = len(stats)
    for i, (value, label) in enumerate(stats):
        cx = (i + 0.5) / n
        ax.text(cx, 0.62, value, ha="center", va="center", fontsize=15,
                fontweight="bold", color=t["blue"], transform=ax.transAxes)
        ax.text(cx, 0.16, label, ha="center", va="center", fontsize=9,
                color=t["muted"], transform=ax.transAxes)
        if i:
            ax.axvline(i / n, ymin=0.15, ymax=0.85, color=t["grid"], linewidth=0.8)
    save(fig, out_dir, "summary", theme_name)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True, type=Path)
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--ext", default="svg", choices=["svg", "png"],
                    help="png is for local visual verification only")
    args = ap.parse_args()
    global EXT
    EXT = args.ext
    args.out_dir.mkdir(parents=True, exist_ok=True)

    daily = load_daily(args.data_dir)
    for theme_name, t in THEMES.items():
        print(f"theme: {theme_name}")
        chart_summary(daily, args.data_dir, args.out_dir, theme_name, t)
        chart_loc(daily, args.out_dir, theme_name, t)
        chart_churn(daily, args.out_dir, theme_name, t)
        chart_repos(daily, args.out_dir, theme_name, t)
        chart_languages(args.data_dir, args.out_dir, theme_name, t)
        chart_focus(daily, args.out_dir, theme_name, t)
        chart_punchcard(args.data_dir, args.out_dir, theme_name, t)
        chart_prs(args.data_dir, args.out_dir, theme_name, t)
        chart_treemap(args.data_dir, args.out_dir, theme_name, t)


if __name__ == "__main__":
    main()
