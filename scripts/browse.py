#!/usr/bin/env python3
"""
TUI browser for the Specter Chroma DB.

Zero deps beyond stdlib + your existing repo. Reads directly from Chroma
(no API call). Keyboard nav, filter, sort, full-record view.

Usage:
    python scripts/browse.py
    PYTHONPATH=. .venv/bin/python scripts/browse.py

Keys:
    j / ↓        next record
    k / ↑        previous record
    g / Home     jump to top
    G / End      jump to bottom
    PgDn / PgUp  page jump
    Enter / l    open full record (drill in)
    h / ←        back from full record
    /            filter (substring match across visible fields)
    s            cycle sort (citation, state, topic, score-desc, id)
    f            cycle state filter (ALL, CA, TX, FL, PA, ...)
    t            cycle legal_topic filter
    c            clear filters
    r            reload from Chroma
    d            toggle DETAIL mode (lawyer view <-> engineer view)
    q / Esc      quit
"""
from __future__ import annotations
import curses
import os
import sys
import textwrap
from pathlib import Path
from typing import Any

# Make repo importable
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

from api import chroma_store  # noqa: E402


# ---------------------------------------------------------------- data

def fetch_records() -> list[dict[str, Any]]:
    coll = chroma_store.get_collection()
    res = coll.get(include=["metadatas", "documents"])
    out: list[dict[str, Any]] = []
    for rid, meta, doc in zip(res["ids"], res["metadatas"], res["documents"]):
        out.append({
            "id": rid,
            "text": doc,
            **(meta or {}),
        })
    return out


# ---------------------------------------------------------------- view helpers

ROW_FIELDS = ["state_code", "citation", "legal_topic", "topic_confidence", "factors_csv"]
ROW_HEADER = ("ST",  "CITATION",                          "LEGAL TOPIC",                      "CONF",  "RAW FACTOR")
ROW_WIDTHS = (3,     38,                                  28,                                 5,       30)


def format_row(rec: dict[str, Any], cols_total: int) -> str:
    state = (rec.get("state_code") or "??")[:ROW_WIDTHS[0]]
    cite  = (rec.get("citation") or rec.get("id") or "")[:ROW_WIDTHS[1]]
    topic = (rec.get("legal_topic") or "")[:ROW_WIDTHS[2]]
    conf  = rec.get("topic_confidence")
    conf_s = f"{conf:.2f}" if isinstance(conf, (int, float)) else "—"
    factor = (rec.get("factors_csv") or "")[:ROW_WIDTHS[4]]
    line = (
        f" {state:<{ROW_WIDTHS[0]}} "
        f"{cite:<{ROW_WIDTHS[1]}} "
        f"{topic:<{ROW_WIDTHS[2]}} "
        f"{conf_s:>{ROW_WIDTHS[3]}} "
        f"{factor:<{ROW_WIDTHS[4]}}"
    )
    return line[: cols_total - 1]


def header_line(cols_total: int) -> str:
    line = (
        f" {ROW_HEADER[0]:<{ROW_WIDTHS[0]}} "
        f"{ROW_HEADER[1]:<{ROW_WIDTHS[1]}} "
        f"{ROW_HEADER[2]:<{ROW_WIDTHS[2]}} "
        f"{ROW_HEADER[3]:>{ROW_WIDTHS[3]}} "
        f"{ROW_HEADER[4]:<{ROW_WIDTHS[4]}}"
    )
    return line[: cols_total - 1]


def safe_addstr(win, y, x, s, attr=0):
    """Write a string into the curses window without raising at the edges."""
    max_y, max_x = win.getmaxyx()
    if y < 0 or y >= max_y or x >= max_x:
        return
    s = s[: max(0, max_x - x - 1)]
    try:
        win.addstr(y, x, s, attr)
    except curses.error:
        pass


# ---------------------------------------------------------------- state

class State:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self.all = records
        self.filter_text: str = ""
        self.state_filter: str = "ALL"
        self.topic_filter: str = "ALL"
        self.sort_mode: str = "citation"
        self.sort_modes = ["citation", "state", "topic", "confidence-desc", "id"]
        self.cursor: int = 0
        self.scroll: int = 0
        self.visible: list[dict[str, Any]] = []
        self.recompute()

    @property
    def states(self) -> list[str]:
        s = sorted({r.get("state_code") or "??" for r in self.all})
        return ["ALL"] + s

    @property
    def topics(self) -> list[str]:
        s = sorted({r.get("legal_topic") or "(none)" for r in self.all})
        return ["ALL"] + s

    def cycle(self, current: str, options: list[str]) -> str:
        i = options.index(current) if current in options else 0
        return options[(i + 1) % len(options)]

    def recompute(self) -> None:
        rows = self.all
        if self.state_filter != "ALL":
            rows = [r for r in rows if r.get("state_code") == self.state_filter]
        if self.topic_filter != "ALL":
            t = self.topic_filter if self.topic_filter != "(none)" else None
            rows = [r for r in rows if (r.get("legal_topic") or None) == t]
        if self.filter_text:
            q = self.filter_text.lower()
            def hit(r):
                blob = " ".join(str(r.get(k, "")) for k in
                                ("citation", "legal_topic", "factors_csv",
                                 "state_code", "text", "title"))
                return q in blob.lower()
            rows = [r for r in rows if hit(r)]

        sm = self.sort_mode
        if sm == "citation":
            rows.sort(key=lambda r: (r.get("state_code") or "", r.get("citation") or ""))
        elif sm == "state":
            rows.sort(key=lambda r: (r.get("state_code") or "", r.get("citation") or ""))
        elif sm == "topic":
            rows.sort(key=lambda r: (r.get("legal_topic") or "~", r.get("citation") or ""))
        elif sm == "confidence-desc":
            rows.sort(key=lambda r: -(r.get("topic_confidence") or 0))
        elif sm == "id":
            rows.sort(key=lambda r: r.get("id") or "")
        self.visible = rows
        self.cursor = max(0, min(self.cursor, len(self.visible) - 1)) if self.visible else 0
        self.scroll = max(0, min(self.scroll, max(0, len(self.visible) - 1)))


# ---------------------------------------------------------------- screens

def draw_list(stdscr, st: State) -> None:
    stdscr.erase()
    rows, cols = stdscr.getmaxyx()

    # Title bar
    title = " Specter — Chroma Browser "
    safe_addstr(stdscr, 0, 0, title.ljust(cols - 1), curses.A_REVERSE)

    # Filter bar
    info = (
        f" total={len(st.all)}  shown={len(st.visible)}  "
        f"state={st.state_filter}  topic={st.topic_filter}  "
        f"sort={st.sort_mode}  filter='{st.filter_text}'"
    )
    safe_addstr(stdscr, 1, 0, info.ljust(cols - 1), curses.A_DIM)

    # Column header
    safe_addstr(stdscr, 2, 0, header_line(cols), curses.A_BOLD | curses.A_UNDERLINE)

    # Rows window
    list_top = 3
    list_bot = rows - 2
    list_h = list_bot - list_top
    if list_h < 1:
        return

    # Adjust scroll to keep cursor in view
    if st.cursor < st.scroll:
        st.scroll = st.cursor
    if st.cursor >= st.scroll + list_h:
        st.scroll = st.cursor - list_h + 1

    for i in range(list_h):
        idx = st.scroll + i
        if idx >= len(st.visible):
            break
        rec = st.visible[idx]
        line = format_row(rec, cols)
        attr = curses.A_REVERSE if idx == st.cursor else 0
        # Color hint: low confidence dim
        conf = rec.get("topic_confidence")
        if isinstance(conf, (int, float)) and conf < 0.7 and not (attr & curses.A_REVERSE):
            attr |= curses.A_DIM
        safe_addstr(stdscr, list_top + i, 0, line.ljust(cols - 1), attr)

    # Footer / help
    help_line = (
        " j/k move   Enter view   /=filter   s=sort   f=state   t=topic   "
        "c=clear   r=reload   q=quit "
    )
    safe_addstr(stdscr, rows - 1, 0, help_line.ljust(cols - 1), curses.A_REVERSE)


# Lawyer-mode whitelist: only show what an attorney actually wants to see.
# Order matters — these are rendered top-to-bottom.
LAWYER_FIELDS: list[tuple[str, str]] = [
    ("citation",          "Citation"),
    ("jurisdiction",      "Jurisdiction"),
    ("title",             "Title"),
    ("legal_topic",       "Legal Topic"),
    ("topic_confidence",  "Topic Confidence"),
    ("factors_csv",       "Raw Factor (per state)"),
    ("document_type",     "Document Type"),
    ("authority_source",  "Issuing Authority"),
    ("text",              "Statute Text"),
    ("source_url",        "Source"),
]

# Engineer-mode whitelist: show core fields first (ordered), then EVERYTHING else.
ENGINEER_PRIORITY = [
    "id", "citation", "state_code", "jurisdiction_norm", "jurisdiction",
    "code", "section", "title",
    "legal_topic", "topic_confidence",
    "factors_csv",
    "document_type", "authority_source",
    "pi_relevant", "confidence",
    "source_url",
    "text",
]


def _format_value(key: str, v: Any) -> str:
    if key == "topic_confidence" and isinstance(v, (int, float)):
        return f"{v * 100:.0f}%  ({v:.2f})"
    if isinstance(v, bool):
        return "yes" if v else "no"
    return str(v)


def draw_detail(stdscr, rec: dict[str, Any], mode_engineer: bool = False) -> None:
    stdscr.erase()
    rows, cols = stdscr.getmaxyx()

    title = f" Record: {rec.get('citation') or rec.get('id')} "
    safe_addstr(stdscr, 0, 0, title.ljust(cols - 1), curses.A_REVERSE)
    badge = " [engineer view] " if mode_engineer else " [lawyer view] "
    safe_addstr(stdscr, 0, max(0, cols - len(badge) - 1), badge, curses.A_REVERSE | curses.A_BOLD)

    if not mode_engineer:
        # ---------- LAWYER VIEW ----------
        y = 2
        for key, label in LAWYER_FIELDS:
            v = rec.get(key)
            if v is None or v == "":
                continue
            label_str = f"  {label:<22s}"
            if key == "text":
                safe_addstr(stdscr, y, 0, label_str, curses.A_BOLD)
                y += 1
                wrap_w = max(20, cols - 6)
                wrapped = textwrap.fill(str(v), width=wrap_w,
                                         initial_indent="    ", subsequent_indent="    ")
                for line in wrapped.split("\n"):
                    if y >= rows - 2:
                        break
                    safe_addstr(stdscr, y, 0, line)
                    y += 1
            else:
                sval = _format_value(key, v)
                safe_addstr(stdscr, y, 0, label_str, curses.A_BOLD)
                safe_addstr(stdscr, y, len(label_str), sval)
                y += 1
            if y >= rows - 2:
                break
    else:
        # ---------- ENGINEER VIEW ----------
        # Show ENGINEER_PRIORITY first, then everything else (including factor_* flags)
        seen = set()
        ordered: list[str] = []
        for k in ENGINEER_PRIORITY:
            if k in rec:
                ordered.append(k); seen.add(k)
        for k in sorted(rec.keys()):
            if k not in seen:
                ordered.append(k)

        y = 2
        for k in ordered:
            v = rec.get(k)
            if v is None or v == "":
                continue
            label = f"  {k:<28s}"
            if k == "text":
                safe_addstr(stdscr, y, 0, label, curses.A_BOLD)
                y += 1
                wrap_w = max(20, cols - 6)
                wrapped = textwrap.fill(str(v), width=wrap_w,
                                         initial_indent="    ", subsequent_indent="    ")
                for line in wrapped.split("\n"):
                    if y >= rows - 2:
                        break
                    safe_addstr(stdscr, y, 0, line)
                    y += 1
            else:
                sval = str(v)
                attr = curses.A_DIM if k.startswith("factor_") else 0
                safe_addstr(stdscr, y, 0, label, curses.A_BOLD | attr)
                safe_addstr(stdscr, y, len(label), sval, attr)
                y += 1
            if y >= rows - 2:
                break

    footer = " h / ← back     d toggle lawyer/engineer view     q quit "
    safe_addstr(stdscr, rows - 1, 0, footer.ljust(cols - 1), curses.A_REVERSE)


def prompt(stdscr, label: str, initial: str = "") -> str:
    rows, cols = stdscr.getmaxyx()
    curses.echo()
    curses.curs_set(1)
    safe_addstr(stdscr, rows - 1, 0, (" " + label + " ").ljust(cols - 1), curses.A_REVERSE)
    stdscr.move(rows - 1, len(label) + 2)
    stdscr.clrtoeol()
    try:
        s = stdscr.getstr(rows - 1, len(label) + 2, max(1, cols - len(label) - 4)).decode("utf-8", "ignore")
    except KeyboardInterrupt:
        s = initial
    curses.noecho()
    curses.curs_set(0)
    return s


# ---------------------------------------------------------------- main loop

def app(stdscr, st: State) -> None:
    curses.curs_set(0)
    stdscr.keypad(True)

    mode = "list"
    detail_rec: dict[str, Any] | None = None
    detail_engineer = False  # default to lawyer view

    while True:
        if mode == "list":
            draw_list(stdscr, st)
        else:
            draw_detail(stdscr, detail_rec or {}, mode_engineer=detail_engineer)
        stdscr.refresh()

        try:
            ch = stdscr.getch()
        except KeyboardInterrupt:
            return

        if mode == "list":
            if ch in (ord("q"), 27):  # esc
                return
            elif ch in (ord("j"), curses.KEY_DOWN):
                if st.visible:
                    st.cursor = min(st.cursor + 1, len(st.visible) - 1)
            elif ch in (ord("k"), curses.KEY_UP):
                st.cursor = max(0, st.cursor - 1)
            elif ch in (ord("g"), curses.KEY_HOME):
                st.cursor = 0
            elif ch in (ord("G"), curses.KEY_END):
                if st.visible:
                    st.cursor = len(st.visible) - 1
            elif ch == curses.KEY_NPAGE:
                rows, _ = stdscr.getmaxyx()
                st.cursor = min(len(st.visible) - 1, st.cursor + (rows - 5))
            elif ch == curses.KEY_PPAGE:
                rows, _ = stdscr.getmaxyx()
                st.cursor = max(0, st.cursor - (rows - 5))
            elif ch in (curses.KEY_ENTER, 10, 13, ord("l"), curses.KEY_RIGHT):
                if st.visible:
                    detail_rec = st.visible[st.cursor]
                    mode = "detail"
            elif ch == ord("/"):
                txt = prompt(stdscr, "filter:", st.filter_text)
                st.filter_text = txt
                st.recompute()
            elif ch == ord("s"):
                st.sort_mode = st.cycle(st.sort_mode, st.sort_modes)
                st.recompute()
            elif ch == ord("f"):
                st.state_filter = st.cycle(st.state_filter, st.states)
                st.recompute()
            elif ch == ord("t"):
                st.topic_filter = st.cycle(st.topic_filter, st.topics)
                st.recompute()
            elif ch == ord("c"):
                st.filter_text = ""
                st.state_filter = "ALL"
                st.topic_filter = "ALL"
                st.recompute()
            elif ch == ord("r"):
                st.all = fetch_records()
                st.recompute()
        else:  # detail
            if ch in (ord("q"), 27):
                return
            elif ch in (ord("h"), curses.KEY_LEFT, curses.KEY_ENTER, 10, 13):
                mode = "list"
            elif ch == ord("d"):
                detail_engineer = not detail_engineer


def main() -> None:
    print("Loading Chroma...", flush=True)
    records = fetch_records()
    if not records:
        print("No records in Chroma. Run `make seed && make tag && make load` first.")
        return
    print(f"Loaded {len(records)} records. Starting browser...", flush=True)
    st = State(records)

    # Make backspace work in the prompt
    os.environ.setdefault("ESCDELAY", "25")
    curses.wrapper(app, st)


if __name__ == "__main__":
    main()
