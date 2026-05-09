"""
Specter HTTP API. Lock this contract early — every other track depends on it.

Endpoints:
    GET  /healthz
    GET  /lookup?citation=...
    GET  /search?q=...&state=CA&factor=DUI/DWI&legal_topic=speeding&k=10
    POST /ask        { "question": "..." }   # vector search wrapper for chat agents
    GET  /factors    # list the 17 raw contributing-factor categories
    GET  /topics     # list the normalized legal_topic abstraction layer
"""
from __future__ import annotations
from typing import Optional
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from dotenv import load_dotenv

from harvester.schema import CONTRIBUTING_FACTORS
from tagger.enrich import LEGAL_TOPICS
from api.voyage_embed import embed
from api import chroma_store
from api import organizer
import wiki as authority_wiki

load_dotenv()

app = FastAPI(title="Specter Harvester API", version="0.2.0")


@app.get("/healthz")
def healthz():
    coll = chroma_store.get_collection()
    return {
        "ok": True,
        "collection": coll.name,
        "count": coll.count(),
        "canada_collection": "pi_cases",
        "canada_count": chroma_store.canada_count(),
    }


# ---- Canada / case_stressor routing -----------------------------------

CANADA_HINTS = (
    "canada", "canadian", "ontario", "quebec", "british columbia", "bc",
    "alberta", "manitoba", "saskatchewan", "nova scotia", "new brunswick",
    "newfoundland", "yukon", "toronto", "montreal", "vancouver", "calgary",
    "edmonton", "ottawa", "canlii", "onsc", "onca", "scc",
)


def _wants_canada(
    *,
    text: Optional[str] = None,
    jurisdiction: Optional[str] = None,
    state: Optional[str] = None,
) -> bool:
    """Heuristic: does the user want the Canada / case_stressor collection?"""
    if jurisdiction and jurisdiction.lower() in ("canada", "canadian"):
        return True
    if state and state.upper() in ("CA-CAN", "CAN"):
        return True
    if text:
        t = text.lower()
        return any(h in t for h in CANADA_HINTS)
    return False


@app.get("/factors")
def factors():
    """Raw contributing-factor schema from the released CSV."""
    return {"factors": CONTRIBUTING_FACTORS}


@app.get("/topics")
def topics():
    """Normalized legal-reasoning topics — the semantic abstraction layer."""
    return {"topics": LEGAL_TOPICS}


@app.get("/sources")
def sources(
    state: Optional[str] = Query(None, description="2-letter state code, e.g. CA"),
    kind: Optional[str] = Query(None, description="primary_statute | case_law | bar_association | court_system | federal_dataset | federal_agency | state_agency"),
):
    """Catalog of every authoritative source we trust."""
    items = authority_wiki.load_sources()
    if state:
        items = [s for s in items if (s.get("state_code") or "").upper() == state.upper()]
    if kind:
        items = [s for s in items if s.get("kind") == kind]
    return {
        "count": len(items),
        "kinds": authority_wiki.kinds(),
        "jurisdictions": authority_wiki.jurisdictions(),
        "sources": items,
    }


@app.get("/authority")
def authority(
    need: Optional[str] = Query(None, description="Substring match of a research need (e.g. 'case law', 'damages', 'court rules')"),
    legal_topic: Optional[str] = Query(None, description="Look up the authority ladder for one of our normalized topics"),
    jurisdiction: Optional[str] = Query(None, description="Full state name (California, Texas, ...)"),
    state: Optional[str] = Query(None, description="2-letter state code (CA, TX, ...) for topic routes"),
):
    """
    "Which sources are authoritative for what." The wiki's actual answer.

    - Pass `need` to find sources by research-need substring
      (e.g. need="case law", need="damages", need="court rules")
    - Pass `legal_topic` to get the full source ladder for a topic
      (e.g. legal_topic="DUI-related behavior" + state=CA)
    """
    if legal_topic:
        route = authority_wiki.route_for_topic(legal_topic, jurisdiction=jurisdiction, state_code=state)
        if not route:
            raise HTTPException(404, f"no authority route for legal_topic: {legal_topic!r}")
        return route
    if need is not None:
        return {"routes": authority_wiki.route_for_need(need, jurisdiction=jurisdiction)}
    # Default: return the table of all routes.
    return {
        "routes": authority_wiki.route_for_need("", jurisdiction=jurisdiction),
    }


@app.get("/lookup")
def lookup(citation: str = Query(..., description="Exact citation, e.g. 'Cal. Veh. Code § 23152(a)'")):
    rec = chroma_store.lookup_by_citation(citation)
    if not rec:
        raise HTTPException(404, f"no record for citation: {citation}")
    return rec


@app.get("/search")
def search(
    q: str = Query(..., description="Natural-language query"),
    state: Optional[str] = Query(None, description="2-letter state code, e.g. CA. Use CA-CAN for Canada."),
    factor: Optional[str] = Query(None, description="Raw contributing factor (17-cat)"),
    legal_topic: Optional[str] = Query(None, description="Normalized legal topic (abstraction layer)"),
    jurisdiction: Optional[str] = Query(None, description="Full jurisdiction name. Use 'Canada' to route to the case_stressor collection."),
    document_type: Optional[str] = Query(None, description="statute | regulation | case_law | guidance | dataset"),
    authority_source: Optional[str] = Query(None, description="state_legislature | DMV | court_system | federal_agency"),
    min_topic_confidence: Optional[float] = Query(None, ge=0.0, le=1.0),
    pi_only: bool = False,
    k: int = 10,
):
    if factor and factor not in CONTRIBUTING_FACTORS:
        raise HTTPException(400, f"unknown factor: {factor!r}. See /factors")
    if legal_topic and legal_topic not in LEGAL_TOPICS:
        raise HTTPException(400, f"unknown legal_topic: {legal_topic!r}. See /topics")

    qvec = embed([q], input_type="query")[0]

    # ---- Routing: if the query is about Canada, hit the case_stressor DB.
    use_canada = _wants_canada(text=q, jurisdiction=jurisdiction, state=state)
    if use_canada:
        results = chroma_store.canada_search(qvec, k=k)
        return {
            "query": q,
            "collection": "canada_pi_cases",
            "filters": {
                "state": state, "jurisdiction": jurisdiction,
            },
            "results": results,
        }

    results = chroma_store.search(
        qvec,
        state=state,
        factor=factor,
        pi_only=pi_only,
        k=k,
        legal_topic=legal_topic,
        jurisdiction=jurisdiction,
        document_type=document_type,
        authority_source=authority_source,
        min_topic_confidence=min_topic_confidence,
    )
    return {
        "query": q,
        "collection": "specter_statutes",
        "filters": {
            "state": state,
            "factor": factor,
            "legal_topic": legal_topic,
            "jurisdiction": jurisdiction,
            "document_type": document_type,
            "authority_source": authority_source,
            "min_topic_confidence": min_topic_confidence,
            "pi_only": pi_only,
        },
        "results": results,
    }


class AskBody(BaseModel):
    question: str
    state: Optional[str] = None
    factor: Optional[str] = None
    legal_topic: Optional[str] = None
    jurisdiction: Optional[str] = None
    document_type: Optional[str] = None
    authority_source: Optional[str] = None
    min_topic_confidence: Optional[float] = None
    pi_only: bool = False
    k: int = 8


# ============================================================================
# Organizer — the paralegal workspace
# ============================================================================

@app.get("/comparables")
def comparables(
    state: Optional[str] = Query(None, description="2-letter state code"),
    injury: Optional[str] = Query(None, description="substring match in injury_type"),
    defendant: Optional[str] = Query(None, description="substring match in defendant_type"),
    min_amount: Optional[int] = Query(None, ge=0),
    max_amount: Optional[int] = Query(None, ge=0),
    year_from: Optional[int] = Query(None, ge=1990, le=2100),
    year_to: Optional[int] = Query(None, ge=1990, le=2100),
    sort: str = Query("amount-desc", description="amount-desc | amount-asc | year-desc | year-asc | state"),
    limit: int = Query(20, ge=1, le=200),
):
    """Sortable damages-comparables for the Organizer."""
    return organizer.search_comparables(
        state_code=state,
        injury_substring=injury,
        defendant_type_substring=defendant,
        min_amount=min_amount,
        max_amount=max_amount,
        year_from=year_from,
        year_to=year_to,
        sort=sort,
        limit=limit,
    )


class OrganizeBody(BaseModel):
    description: str
    state: Optional[str] = None
    legal_topic: Optional[str] = None
    k_statutes: int = 8
    k_comparables: int = 10


@app.post("/organize")
def organize(body: OrganizeBody):
    """
    Full Organizer pass on a case description:
      1. Pull applicable statutes via /search (semantic + structured filters)
      2. Pull damages comparables via state filter
      3. Run gap-detection via Claude on the case description
    Returns one structured paralegal-grade workspace JSON blob.
    """
    # 1) Statutes
    qvec = embed([body.description], input_type="query")[0]
    statutes = chroma_store.search(
        qvec,
        state=body.state,
        legal_topic=body.legal_topic,
        k=body.k_statutes,
    )

    # 2) Comparables
    comps = organizer.search_comparables(
        state_code=body.state,
        sort="amount-desc",
        limit=body.k_comparables,
    )

    # 3) Gaps (Claude)
    try:
        gaps = organizer.detect_gaps(body.description)
    except Exception as e:
        gaps = {
            "have": [], "missing": [], "uncertain": [],
            "readiness_score": 0.0,
            "next_actions": [],
            "_error": f"{type(e).__name__}: {e}",
        }

    return {
        "description": body.description,
        "filters": {"state": body.state, "legal_topic": body.legal_topic},
        "statutes": statutes,
        "comparables": comps,
        "coverage": gaps,
    }


@app.post("/ask")
def ask(body: AskBody):
    if body.factor and body.factor not in CONTRIBUTING_FACTORS:
        raise HTTPException(400, f"unknown factor: {body.factor!r}. See /factors")
    if body.legal_topic and body.legal_topic not in LEGAL_TOPICS:
        raise HTTPException(400, f"unknown legal_topic: {body.legal_topic!r}. See /topics")

    qvec = embed([body.question], input_type="query")[0]

    use_canada = _wants_canada(text=body.question, jurisdiction=body.jurisdiction, state=body.state)
    if use_canada:
        hits = chroma_store.canada_search(qvec, k=body.k)
        return {"question": body.question, "collection": "canada_pi_cases", "hits": hits}

    hits = chroma_store.search(
        qvec,
        state=body.state,
        factor=body.factor,
        pi_only=body.pi_only,
        k=body.k,
        legal_topic=body.legal_topic,
        jurisdiction=body.jurisdiction,
        document_type=body.document_type,
        authority_source=body.authority_source,
        min_topic_confidence=body.min_topic_confidence,
    )
    return {"question": body.question, "collection": "specter_statutes", "hits": hits}
