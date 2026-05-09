"""
Specter HTTP API. Lock this contract early — every other track depends on it.

Endpoints:
    GET  /healthz
    GET  /lookup?citation=...
    GET  /search?q=...&state=CA&factor=DUI/DWI&k=10&pi_only=true
    POST /ask        { "question": "..." }   # vector search wrapper for chat agents
    GET  /factors    # list the 17 categories (handy for the UI)
"""
from __future__ import annotations
from typing import Optional
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from dotenv import load_dotenv

from harvester.schema import CONTRIBUTING_FACTORS
from api.voyage_embed import embed
from api import chroma_store

load_dotenv()

app = FastAPI(title="Specter Harvester API", version="0.1.0")


@app.get("/healthz")
def healthz():
    coll = chroma_store.get_collection()
    return {"ok": True, "collection": coll.name, "count": coll.count()}


@app.get("/factors")
def factors():
    return {"factors": CONTRIBUTING_FACTORS}


@app.get("/lookup")
def lookup(citation: str = Query(..., description="Exact citation, e.g. 'Cal. Veh. Code § 23152(a)'")):
    rec = chroma_store.lookup_by_citation(citation)
    if not rec:
        raise HTTPException(404, f"no record for citation: {citation}")
    return rec


@app.get("/search")
def search(
    q: str = Query(..., description="Natural-language query"),
    state: Optional[str] = None,
    factor: Optional[str] = None,
    pi_only: bool = False,
    k: int = 10,
):
    if factor and factor not in CONTRIBUTING_FACTORS:
        raise HTTPException(400, f"unknown factor: {factor!r}. See /factors")
    qvec = embed([q], input_type="query")[0]
    return {
        "query": q,
        "filters": {"state": state, "factor": factor, "pi_only": pi_only},
        "results": chroma_store.search(qvec, state=state, factor=factor, pi_only=pi_only, k=k),
    }


class AskBody(BaseModel):
    question: str
    state: Optional[str] = None
    factor: Optional[str] = None
    k: int = 8


@app.post("/ask")
def ask(body: AskBody):
    qvec = embed([body.question], input_type="query")[0]
    hits = chroma_store.search(qvec, state=body.state, factor=body.factor, k=body.k)
    return {"question": body.question, "hits": hits}
