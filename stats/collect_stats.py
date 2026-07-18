#!/usr/bin/env python3
"""Collect BTNET org-wide developer stats from local clones of every org repo.

Outputs CSVs under data/ (all aggregate; repo names are never written except
anonymized ranks in repo_sizes.csv):

  daily.csv       date, loc, repos, additions, deletions,
                  fe_changed, be_changed, infra_changed, commits
  languages.csv   language, lines            (snapshot of latest sample)
  repo_sizes.csv  rank, lines                (snapshot, anonymized)
  punchcard.csv   weekday, hour, commits     (snapshot, all history, UTC)
  prs_weekly.csv  week_start, prs_merged     (snapshot, needs gh + GH_TOKEN)

Line counting = raw newline count of every tracked non-binary blob on the
default branch, sampled at the last commit of each UTC day. Submodules
(gitlinks) are skipped, so vendored third-party submodule code is excluded.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ORG = "BasisTradingDotNet"
ORG_CREATED = dt.date(2026, 5, 7)

FRONTEND_EXTS = {
    "ts", "tsx", "js", "jsx", "mjs", "cjs", "css", "scss", "sass", "less",
    "html", "vue", "svelte",
}
BACKEND_EXTS = {
    "rs", "py", "sol", "sql", "go", "java", "c", "cc", "cpp", "h", "hpp",
}
# Everything else (toml/yaml/md/sh/json/lockfiles/...) = infra & docs.

# Committed third-party dependency dirs are excluded from all line stats
# (matching the "exclude vendored code" rule; git submodules are excluded
# automatically since gitlinks carry no tree content).
VENDORED_DIRS = {"node_modules", "vendor", "vendors", ".venv", "venv", "site-packages"}


def is_vendored(path: str) -> bool:
    return any(part in VENDORED_DIRS for part in path.split("/"))

LANG_BY_EXT = {
    "rs": "Rust",
    "py": "Python",
    "ts": "TypeScript", "tsx": "TypeScript",
    "js": "JavaScript", "jsx": "JavaScript", "mjs": "JavaScript", "cjs": "JavaScript",
    "sol": "Solidity",
    "sh": "Shell", "bash": "Shell",
    "sql": "SQL",
    "css": "CSS", "scss": "CSS", "sass": "CSS", "less": "CSS",
    "html": "HTML",
    "md": "Markdown",
    "toml": "TOML",
    "yml": "YAML", "yaml": "YAML",
    "json": "JSON",
    "xml": "XML",
    "prisma": "Prisma",
    "ipynb": "Jupyter",
    "txt": "Text",
    "csv": "Data",
    "tf": "Terraform",
}


def run(cmd: list[str], cwd: Path | None = None) -> str:
    return subprocess.run(
        cmd, cwd=cwd, check=True, capture_output=True, text=True,
        env={**os.environ, "TZ": "UTC"},
    ).stdout


def ext_of(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    if name.lower() in ("dockerfile", "makefile", "justfile"):
        return name.lower()
    if "." not in name:
        return ""
    return name.rsplit(".", 1)[-1].lower()


def category_of(path: str) -> str:
    ext = ext_of(path)
    if ext in FRONTEND_EXTS:
        return "fe"
    if ext in BACKEND_EXTS:
        return "be"
    return "infra"


def default_branch(repo: Path) -> str:
    out = run(["git", "symbolic-ref", "refs/remotes/origin/HEAD"], cwd=repo).strip()
    return out.rsplit("/", 1)[-1]


def commits_with_dates(repo: Path, branch: str) -> list[tuple[str, dt.datetime]]:
    """All commits on the default branch, oldest first, with UTC committer time."""
    out = run(["git", "log", f"origin/{branch}", "--format=%H %cI", "--reverse"], cwd=repo)
    commits = []
    for line in out.splitlines():
        sha, iso = line.split(" ", 1)
        ts = dt.datetime.fromisoformat(iso).astimezone(dt.timezone.utc)
        commits.append((sha, ts))
    return commits


class BlobCounter:
    """Counts raw lines per blob via one long-lived `git cat-file --batch`.

    Line counts are cached per blob SHA, so daily samples that share most of
    their tree are cheap. Binary blobs (NUL in the first 8000 bytes) -> None.
    """

    def __init__(self, repo: Path):
        self.cache: dict[str, int | None] = {}
        self.proc = subprocess.Popen(
            ["git", "cat-file", "--batch"], cwd=repo,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        )

    def lines(self, sha: str) -> int | None:
        if sha in self.cache:
            return self.cache[sha]
        assert self.proc.stdin and self.proc.stdout
        self.proc.stdin.write(f"{sha}\n".encode())
        self.proc.stdin.flush()
        header = self.proc.stdout.readline().decode().strip()
        parts = header.split()
        if len(parts) != 3:  # "<sha> missing"
            self.cache[sha] = None
            return None
        size = int(parts[2])
        body = self.proc.stdout.read(size + 1)[:size]  # +1 trailing LF
        result: int | None
        if b"\x00" in body[:8000]:
            result = None
        else:
            result = body.count(b"\n")
        self.cache[sha] = result
        return result

    def close(self) -> None:
        if self.proc.stdin:
            self.proc.stdin.close()
        self.proc.wait()


def tree_files(repo: Path, commit: str) -> list[tuple[str, str]]:
    """(blob_sha, path) for every regular file at `commit`; gitlinks skipped."""
    out = run(["git", "ls-tree", "-r", commit], cwd=repo)
    files = []
    for line in out.splitlines():
        meta, path = line.split("\t", 1)
        mode, otype, sha = meta.split()
        if otype != "blob":  # skips 160000 commit entries (submodules)
            continue
        if is_vendored(path):
            continue
        files.append((sha, path))
    return files


def daily_churn(repo: Path, branch: str):
    """Per-UTC-day additions/deletions (total and per category) and commit
    timestamps, from --numstat on the default branch (merges excluded)."""
    out = run(
        ["git", "log", f"origin/{branch}", "--no-merges", "--numstat", "--format=@%cI"],
        cwd=repo,
    )
    churn: dict[dt.date, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    timestamps: list[dt.datetime] = []
    day: dt.date | None = None
    for line in out.splitlines():
        if not line:
            continue
        if line.startswith("@"):
            ts = dt.datetime.fromisoformat(line[1:]).astimezone(dt.timezone.utc)
            timestamps.append(ts)
            day = ts.date()
            continue
        parts = line.split("\t")
        if len(parts) != 3 or day is None:
            continue
        add_s, del_s, path = parts
        if add_s == "-" or del_s == "-":  # binary
            continue
        if is_vendored(path):
            continue
        adds, dels = int(add_s), int(del_s)
        d = churn[day]
        d["additions"] += adds
        d["deletions"] += dels
        d[category_of(path) + "_changed"] += adds + dels
    return churn, timestamps


def merged_prs_weekly() -> dict[dt.date, int] | None:
    """PRs merged per ISO week across the org, via gh (best effort)."""
    try:
        names = json.loads(run([
            "gh", "repo", "list", ORG, "--limit", "200", "--json", "name",
        ]))
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"warning: skipping PR stats ({e})", file=sys.stderr)
        return None
    weekly: dict[dt.date, int] = defaultdict(int)
    for entry in names:
        try:
            prs = json.loads(run([
                "gh", "pr", "list", "-R", f"{ORG}/{entry['name']}",
                "--state", "merged", "--limit", "2000", "--json", "mergedAt",
            ]))
        except subprocess.CalledProcessError as e:
            print(f"warning: pr list failed for {entry['name']}: {e}", file=sys.stderr)
            continue
        for pr in prs:
            merged = dt.datetime.fromisoformat(pr["mergedAt"].replace("Z", "+00:00"))
            d = merged.astimezone(dt.timezone.utc).date()
            weekly[d - dt.timedelta(days=d.weekday())] += 1
    return dict(weekly)


def repo_created_dates() -> list[dt.date]:
    entries = json.loads(run([
        "gh", "repo", "list", ORG, "--limit", "200", "--json", "createdAt",
    ]))
    return [
        dt.datetime.fromisoformat(e["createdAt"].replace("Z", "+00:00")).date()
        for e in entries
    ]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repos-dir", required=True, type=Path)
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--skip-prs", action="store_true")
    args = ap.parse_args()

    repos = sorted(
        p for p in args.repos_dir.iterdir() if (p / ".git").exists()
    )
    if not repos:
        sys.exit(f"no git repos found in {args.repos_dir}")
    print(f"{len(repos)} repos found")

    today = dt.datetime.now(dt.timezone.utc).date()
    last_day = today - dt.timedelta(days=1)  # last complete UTC day
    days = [
        ORG_CREATED + dt.timedelta(days=i)
        for i in range((last_day - ORG_CREATED).days + 1)
    ]

    loc_by_day: dict[dt.date, int] = defaultdict(int)
    churn_by_day: dict[dt.date, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    commits_by_day: dict[dt.date, int] = defaultdict(int)
    punchcard: dict[tuple[int, int], int] = defaultdict(int)
    lang_lines: dict[str, int] = defaultdict(int)
    repo_totals: list[int] = []

    for repo in repos:
        branch = default_branch(repo)
        commits = commits_with_dates(repo, branch)
        counter = BlobCounter(repo)

        # Pick the last commit at or before the end of each sampled UTC day.
        sample: dict[dt.date, str] = {}
        ci = -1
        for day in days:
            end = dt.datetime.combine(
                day, dt.time(23, 59, 59, 999999), tzinfo=dt.timezone.utc
            )
            while ci + 1 < len(commits) and commits[ci + 1][1] <= end:
                ci += 1
            if ci >= 0:
                sample[day] = commits[ci][0]

        tree_cache: dict[str, int] = {}
        latest_commit = None
        for day, commit in sample.items():
            if commit not in tree_cache:
                total = 0
                for sha, _path in tree_files(repo, commit):
                    n = counter.lines(sha)
                    if n is not None:
                        total += n
                tree_cache[commit] = total
            loc_by_day[day] += tree_cache[commit]
            latest_commit = commit

        if latest_commit:
            repo_total = 0
            for sha, path in tree_files(repo, latest_commit):
                n = counter.lines(sha)
                if n is None:
                    continue
                repo_total += n
                lang_lines[LANG_BY_EXT.get(ext_of(path), "Other")] += n
            repo_totals.append(repo_total)

        churn, timestamps = daily_churn(repo, branch)
        for day, vals in churn.items():
            for k, v in vals.items():
                churn_by_day[day][k] += v
        for ts in timestamps:
            commits_by_day[ts.date()] += 1
            punchcard[(ts.weekday(), ts.hour)] += 1

        counter.close()
        print(f"  {repo.name}: {len(commits)} commits, latest sample done")

    created = repo_created_dates()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    with open(args.out_dir / "daily.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "date", "loc", "repos", "additions", "deletions",
            "fe_changed", "be_changed", "infra_changed", "commits",
        ])
        for day in days:
            c = churn_by_day.get(day, {})
            w.writerow([
                day.isoformat(),
                loc_by_day.get(day, 0),
                sum(1 for d in created if d <= day),
                c.get("additions", 0),
                c.get("deletions", 0),
                c.get("fe_changed", 0),
                c.get("be_changed", 0),
                c.get("infra_changed", 0),
                commits_by_day.get(day, 0),
            ])

    with open(args.out_dir / "languages.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["language", "lines"])
        for lang, lines in sorted(lang_lines.items(), key=lambda kv: -kv[1]):
            w.writerow([lang, lines])

    with open(args.out_dir / "repo_sizes.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rank", "lines"])
        for i, lines in enumerate(sorted(repo_totals, reverse=True), 1):
            w.writerow([i, lines])

    with open(args.out_dir / "punchcard.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["weekday", "hour", "commits"])
        for (wd, hr), n in sorted(punchcard.items()):
            w.writerow([wd, hr, n])

    if not args.skip_prs:
        weekly = merged_prs_weekly()
        if weekly is not None:
            with open(args.out_dir / "prs_weekly.csv", "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["week_start", "prs_merged"])
                for week in sorted(weekly):
                    w.writerow([week.isoformat(), weekly[week]])

    print(f"wrote CSVs to {args.out_dir}")


if __name__ == "__main__":
    main()
