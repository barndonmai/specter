#!/usr/bin/env python3
"""
Visualize the Chroma DB itself — vectors, clusters, similarity.

Shows what's INSIDE the vector store, not just the metadata schema:
  • Storage footprint on disk
  • Vector norms (sanity check the embeddings are normalized)
  • Topic clusters (how many statutes per legal_topic + their tightness)
  • Cross-topic similarity heatmap (do topics overlap or are they distinct?)
  • Per-state semantic compactness
  • Outlier records (low-confidence or weak-cluster members)
  • A live "show me one record at random with its nearest neighbors"

Usage:
    python scripts/chroma_viz.py
    PYTHONPATH=. .venv/bin/python scripts/chroma_viz.py
"""
from __future__ import annotations
import math
import os
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import numpy as np  # chromadb pulls numpy in
from api import chroma_store


# ------------------------------------------------------------------ ANSI

NO_COLOR = not sys.stdout.isatty() or os.getenv("NO_COLOR")
def c(code, s):  # noqa: E704
    return s if NO_COLOR else f"{code}{s}\033[0m"

B = "\033[1m"; D = "\033[2m"; UND = "\033[4m"
RED = "\033[31m"; GN = "\033[32m"; YL = "\033[33m"
BL = "\033[34m"; MG = "\033[35m"; CY = "\033[36m"; GREY = "\033[90m"


def hr(ch="─"):
    try:
        w = min(os.get_terminal_size().columns, 100)
    except OSError:
        w = 100
    return ch * w


def header(title, color=CY):
    print()
    print(c(color + B, hr("━")))
    print(c(color + B, f"  {title}"))
    print(c(color + B, hr("━")))


def sub(title, color=BL):
    print()
    print(c(color + B, f"┌─ {title} ─" + "─" * max(0, 80 - len(title))))


def bar(n, total, width=30, color=GN):
    if total <= 0:
        return ""
    filled = int(round((n / total) * width))
    return c(color, "█" * filled) + c(GREY, "░" * (width - filled))


def heatmap_cell(v: float) -> str:
    """0..1 cosine similarity → colored block."""
    v = max(0.0, min(1.0, v))
    blocks = " ░▒▓█"
    idx = int(round(v * (len(blocks) - 1)))
    ch = blocks[idx]
    if v >= 0.8:
        return c(GN, ch * 2)
    if v >= 0.6:
        return c(YL, ch * 2)
    if v >= 0.4:
        return c(BL, ch * 2)
    return c(GREY, ch * 2)


def disk_footprint() -> tuple[int, list[tuple[str, int]]]:
    base = Path(os.getenv("CHROMA_PERSIST_DIR", "./.chroma"))
    if not base.exists():
        return 0, []
    total = 0
    sizes: list[tuple[str, int]] = []
    for p in base.rglob("*"):
        if p.is_file():
            try:
                s = p.stat().st_size
                total += s
                sizes.append((str(p.relative_to(base)), s))
            except OSError:
                pass
    sizes.sort(key=lambda x: -x[1])
    return total, sizes


def fmt_bytes(n: int) -> str:
    for unit in ("B", "K", "M", "G"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}T"


# ============================================================================ MAIN

def main() -> None:
    coll = chroma_store.get_collection()
    n = coll.count()
    if n == 0:
        print(c(RED, "Chroma is empty. Run `make seed && make tag && make load` first."))
        return

    res = coll.get(include=["embeddings", "metadatas", "documents"])
    ids = res["ids"]
    embs = np.asarray(res["embeddings"])
    metas = res["metadatas"]
    docs = res["documents"]

    # =========================================================== HEADER

    print()
    print(c(CY + B, hr("━")))
    print(c(CY + B, "    █▀▀ █▄█ █▀█ █▀█ █▀▄▀█ ▄▀█    █░█ █ █▀ █░█ ▄▀█ █░░"))
    print(c(CY + B, "    █▄▄ █░█ █▀▄ █▄█ █░▀░█ █▀█    ▀▄▀ █ ▄█ █▄█ █▀█ █▄▄"))
    print(c(D, "    Vector store deep-dive — what's actually inside Chroma."))
    print(c(CY + B, hr("━")))

    # =========================================================== STORAGE

    header("STORAGE FOOTPRINT", BL)
    total_bytes, files = disk_footprint()
    persist = os.getenv("CHROMA_PERSIST_DIR", "./.chroma")
    print(f"  {c(MG, 'Persist dir:'):<22s} {persist}")
    print(f"  {c(MG, 'Total on disk:'):<22s} {c(B + YL, fmt_bytes(total_bytes))}")
    print(f"  {c(MG, 'Records:'):<22s} {c(B + YL, str(n))}")
    print(f"  {c(MG, 'Vector dimension:'):<22s} {c(B, str(embs.shape[1]))}")
    bytes_per_vec = embs.shape[1] * 4  # float32
    print(f"  {c(MG, 'Bytes per vector:'):<22s} {bytes_per_vec:,d}  (float32)")
    print(f"  {c(MG, 'Vectors total:'):<22s} {fmt_bytes(n * bytes_per_vec)}")

    sub("Top files in .chroma/", BL)
    for path, size in files[:6]:
        print(f"  {fmt_bytes(size):>8s}   {c(D, path)}")

    # =========================================================== VECTOR HEALTH

    header("VECTOR HEALTH  —  are the embeddings well-formed?", GN)

    norms = np.linalg.norm(embs, axis=1)
    print(f"  {c(MG, 'count:'):<22s} {len(norms)}")
    print(f"  {c(MG, 'norm min:'):<22s} {norms.min():.6f}")
    print(f"  {c(MG, 'norm mean:'):<22s} {norms.mean():.6f}")
    print(f"  {c(MG, 'norm max:'):<22s} {norms.max():.6f}")
    if abs(norms.mean() - 1.0) < 0.01 and norms.std() < 0.01:
        print(f"  {c(GN + B, '✓ unit-normalized')} (cosine = dot product, fast lookups).")
    else:
        print(f"  {c(YL, 'note:')} not unit-normalized; cosine still fine, just slower.")

    # Histogram of vector means (cheap "is one dim dominant?" check)
    means = embs.mean(axis=0)
    print()
    print(c(B, "  per-dimension mean (first 64 dims, |x| × 100):"))
    chunk = means[:64]
    line = ""
    for v in chunk:
        h = min(7, int(round(abs(v) * 100)))
        line += "▁▂▃▄▅▆▇█"[h]
    print(f"    {c(D, line)}")
    print(f"    {c(GREY, 'flat ≈ healthy distribution; spikes ≈ anchored on one feature.')}")

    # =========================================================== CLUSTERS

    header("LEGAL-TOPIC CLUSTERS  —  semantic compactness", MG)

    # Group vectors by legal_topic
    by_topic: dict[str, list[int]] = defaultdict(list)
    for i, m in enumerate(metas):
        t = (m or {}).get("legal_topic") or "(none)"
        by_topic[t].append(i)

    rows = []
    for topic, idxs in by_topic.items():
        if len(idxs) < 2:
            continue
        sub_v = embs[idxs]
        # Centroid + mean cosine to centroid
        cen = sub_v.mean(axis=0)
        cen_norm = cen / (np.linalg.norm(cen) + 1e-9)
        unit = sub_v / (np.linalg.norm(sub_v, axis=1, keepdims=True) + 1e-9)
        sims = unit @ cen_norm
        rows.append((topic, len(idxs), float(sims.mean()), float(sims.std())))

    rows.sort(key=lambda r: -r[1])
    hdr = f"  {'topic':<40} {'n':>4}   {'tightness':<14}  {'σ':>6}"
    print(c(B, hdr))
    print(c(GREY, "  " + "─" * 80))
    for topic, count, tightness, sd in rows:
        bar_inner = bar(int(round(tightness * 30)), 30, 30,
                        color=(GN if tightness > 0.65 else (YL if tightness > 0.5 else RED)))
        print(f"  {topic:<40} {count:>4d}   {bar_inner}  {sd:>6.3f}")
    print()
    print(c(D, "  tightness = mean cosine to topic centroid. higher = vectors agree."))
    print(c(D, "  σ        = spread within the cluster. lower = more consistent."))

    # =========================================================== HEATMAP

    header("CROSS-TOPIC SIMILARITY HEATMAP", CY)

    # Centroids only for topics with >= 3 records, capped at 12 for terminal width
    centroids = {}
    for topic, idxs in by_topic.items():
        if len(idxs) >= 3 and topic != "(none)":
            v = embs[idxs].mean(axis=0)
            v /= np.linalg.norm(v) + 1e-9
            centroids[topic] = v
    topics = sorted(centroids.keys(),
                    key=lambda t: -len(by_topic[t]))[:12]
    if len(topics) < 2:
        print(c(GREY, "  not enough topics to plot."))
    else:
        # Header row (numbered)
        print()
        print(c(D, "  Diagonal = self-similarity (1.0). Off-diagonal = how much")
              + c(D, " topic A's centroid"))
        print(c(D, "  resembles topic B's. Tight clusters should be dim off-diagonal."))
        print()
        col_labels = [f"{i+1:>2d}" for i in range(len(topics))]
        print("        " + "  ".join(col_labels))
        for i, t in enumerate(topics):
            row = [f"{i+1:>2d}  {t[:24]:<24}"]
            for j, t2 in enumerate(topics):
                sim = float(centroids[t] @ centroids[t2])
                row.append(heatmap_cell(sim))
            print("  " + "  ".join(row))
        # Legend
        print()
        print("  Legend:  "
              + heatmap_cell(0.2) + c(D, " <0.4  ")
              + heatmap_cell(0.5) + c(D, " 0.4-0.6  ")
              + heatmap_cell(0.7) + c(D, " 0.6-0.8  ")
              + heatmap_cell(0.9) + c(D, " >0.8"))
        print()
        for i, t in enumerate(topics):
            print(f"   {i+1:>2d}  {t}")

    # =========================================================== STATE COMPACTNESS

    header("PER-STATE SEMANTIC COMPACTNESS", BL)
    by_state: dict[str, list[int]] = defaultdict(list)
    for i, m in enumerate(metas):
        s = (m or {}).get("state_code") or "??"
        by_state[s].append(i)

    print(c(B, f"  {'state':<8s}{'n':>5s}   {'tightness':<32s}{'σ':>6s}"))
    for st in sorted(by_state.keys()):
        idxs = by_state[st]
        if len(idxs) < 2:
            continue
        sv = embs[idxs]
        cen = sv.mean(axis=0); cen /= np.linalg.norm(cen) + 1e-9
        unit = sv / (np.linalg.norm(sv, axis=1, keepdims=True) + 1e-9)
        sims = unit @ cen
        t = float(sims.mean()); sd = float(sims.std())
        b = bar(int(round(t * 30)), 30, 30,
                color=(GN if t > 0.6 else (YL if t > 0.45 else RED)))
        print(f"  {st:<8s}{len(idxs):>5d}   {b}  {sd:>6.3f}")

    print()
    print(c(D, "  states with low tightness have BROADER topical coverage,"))
    print(c(D, "  not lower data quality. CA covers many topics; OH covers many topics, etc."))

    # =========================================================== ONE RANDOM RECORD + NEIGHBORS

    header("ONE RANDOM RECORD  +  ITS 5 NEAREST NEIGHBORS", YL)
    pivot = random.randrange(n)
    v = embs[pivot]
    v_unit = v / (np.linalg.norm(v) + 1e-9)
    units = embs / (np.linalg.norm(embs, axis=1, keepdims=True) + 1e-9)
    sims = units @ v_unit
    order = np.argsort(-sims)[:6]  # includes itself

    pm = metas[pivot] or {}
    print(f"  {c(B + YL, 'PIVOT:')} {c(B, pm.get('citation', ids[pivot]))}")
    print(f"  {c(D, 'state:')} {pm.get('state_code'):<5} "
          f"{c(D, 'topic:')} {pm.get('legal_topic') or '(none)':<28s} "
          f"{c(D, 'factor:')} {pm.get('factors_csv') or '(none)'}")
    txt = (docs[pivot] or "").strip()
    if len(txt) > 220:
        txt = txt[:220] + "…"
    print(f"  {c(D, txt)}")
    print()
    print(c(B, "  nearest neighbors (cosine):"))
    for rank, j in enumerate(order):
        if j == pivot:
            continue
        sim = float(sims[j])
        m_ = metas[j] or {}
        print(f"    {sim:>5.3f}   "
              f"{c(B, m_.get('citation', ids[j]) or '?'):<32s}  "
              f"{c(MG, m_.get('legal_topic') or '?'):<28s}  "
              f"{c(D, '['+(m_.get('state_code') or '??')+']')}")

    # =========================================================== OUTLIERS

    header("OUTLIERS  —  weak topic-confidence or low cluster fit", RED)

    # Bottom 8 by topic_confidence
    confs = []
    for i, m in enumerate(metas):
        ct = (m or {}).get("topic_confidence")
        if isinstance(ct, (int, float)):
            confs.append((ct, i))
    confs.sort()
    print(c(B, "  lowest topic_confidence:"))
    for ct, i in confs[:6]:
        m_ = metas[i] or {}
        print(f"    {c(RED, f'{ct:.2f}'):<10s}  {c(B, m_.get('citation', ids[i]) or '?'):<30s}  "
              f"{c(D, m_.get('legal_topic') or '?'):<28s}")

    print()
    print(c(D, "  these are the records most likely to misroute on factor-style queries."))
    print(c(D, "  re-run `python -m tagger.enrich --force` to retry their classification."))

    # =========================================================== TL;DR

    header("ONE-PARAGRAPH TL;DR", CY)
    print(f"""
  {c(B, str(n))} {c(D, 'records,')} {c(B, f'{embs.shape[1]}-dim')} {c(D, 'Voyage embeddings,')} {fmt_bytes(total_bytes)} {c(D, 'on disk.')}
  Vector norms are {c(B, 'unit-length' if abs(norms.mean()-1.0) < 0.01 else 'non-normalized')} (cosine ≈ dot).
  {c(B, str(len([t for t in by_topic if t != '(none)'])))} {c(D, 'legal topics in active use,')} {c(B, f'{len(by_state)} states')}{c(D, '.')}
  Mean within-topic tightness: {c(B, f'{sum(r[2] for r in rows) / max(len(rows),1):.3f}')}
  {c(D, '— higher = embeddings agree on what each topic means.')}
""")


if __name__ == "__main__":
    main()
