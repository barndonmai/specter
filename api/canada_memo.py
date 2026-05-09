"""
Wraps case_stressor/memo.py + query.py so the main FastAPI service can
expose the PI Case Assessment Memo generator over HTTP.

The case_stressor module uses bare imports (`from query import ...`)
AND a relative `./chroma_db` path at module-load time. We work around
both by chdir'ing into case_stressor/ before importing, then chdir'ing
back so we don't disturb the rest of the API.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
CASE_STRESSOR_DIR = ROOT / "case_stressor"

_imported = False
_generate_memo = None         # type: ignore[assignment]
_generate_whatif_memo = None  # type: ignore[assignment]
_query_cases = None           # type: ignore[assignment]
_build_filters = None         # type: ignore[assignment]


def _lazy_import() -> None:
    """Import case_stressor's modules with the right CWD + sys.path."""
    global _imported, _generate_memo, _generate_whatif_memo
    global _query_cases, _build_filters
    if _imported:
        return

    if not CASE_STRESSOR_DIR.exists():
        raise RuntimeError(
            f"case_stressor/ not found at {CASE_STRESSOR_DIR}. "
            "Pull the case_stressor branch first."
        )

    # case_stressor/query.py opens './chroma_db' relative to CWD at import time.
    # Save CWD, switch in, import, switch back.
    saved_cwd = os.getcwd()
    if str(CASE_STRESSOR_DIR) not in sys.path:
        sys.path.insert(0, str(CASE_STRESSOR_DIR))
    try:
        os.chdir(CASE_STRESSOR_DIR)
        from memo import generate_memo as _gm           # type: ignore
        from memo import generate_whatif_memo as _gwm   # type: ignore
        from query import query_cases as _qc            # type: ignore
        from query import build_filters as _bf          # type: ignore
        _generate_memo = _gm
        _generate_whatif_memo = _gwm
        _query_cases = _qc
        _build_filters = _bf
    finally:
        os.chdir(saved_cwd)
    _imported = True


def generate_memo(facts: str, filters: Optional[dict] = None) -> str:
    """Produce a markdown PI Case Assessment Memo for an Ontario fact pattern."""
    _lazy_import()
    saved_cwd = os.getcwd()
    try:
        os.chdir(CASE_STRESSOR_DIR)
        return _generate_memo(facts, filters=filters)
    finally:
        os.chdir(saved_cwd)


def generate_whatif_memo(
    original_facts: str,
    modified_facts: str,
    original_filters: Optional[dict] = None,
    modified_filters: Optional[dict] = None,
) -> str:
    """Produce a markdown 'what if' scenario-comparison memo."""
    _lazy_import()
    saved_cwd = os.getcwd()
    try:
        os.chdir(CASE_STRESSOR_DIR)
        return _generate_whatif_memo(
            original_facts,
            modified_facts,
            original_filters=original_filters,
            modified_filters=modified_filters,
        )
    finally:
        os.chdir(saved_cwd)


def quick_query(facts: str, filters: Optional[dict] = None) -> dict[str, Any]:
    """Return raw {cases, stats} so callers can render their own UI."""
    _lazy_import()
    saved_cwd = os.getcwd()
    try:
        os.chdir(CASE_STRESSOR_DIR)
        return _query_cases(facts, filters=filters)
    finally:
        os.chdir(saved_cwd)


def build_filters(**kwargs) -> Optional[dict]:
    _lazy_import()
    return _build_filters(**kwargs)
