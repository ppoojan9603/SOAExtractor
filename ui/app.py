"""Review UI (ARCHITECTURE §UI, DECISIONS row 13).

FastAPI + one vanilla HTML page. Upload a PDF -> ranked candidate list -> pick
one -> extracted grid beside the rendered page, bbox hover-highlight, footnote
panel, warnings banner. Shares the CLI's pipeline exactly, so the UI and the
committed out/ JSONs can never drift.

    uvicorn soa.ui.app:app --reload      (or: uvicorn ui.app:app --reload)
"""
from __future__ import annotations

import shutil
import tempfile
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, Response

from soa.pipeline import run
from soa.render import render_page_png, SCALE

app = FastAPI(title="SoA Extractor — review")

#: uploaded pdf id -> path (process-local; this is a review tool, not a service)
_UPLOADS: dict[str, Path] = {}
_RESULTS: dict[str, dict] = {}
_TMP = Path(tempfile.gettempdir()) / "soa-extractor-uploads"
_TMP.mkdir(exist_ok=True)

_INDEX = Path(__file__).parent / "index.html"


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    # read per request: this is a local review tool, and caching the page at
    # import time silently serves stale markup after an edit.
    return HTMLResponse(_INDEX.read_text(encoding="utf-8"),
                        headers={"Cache-Control": "no-store"})


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)) -> JSONResponse:
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "please upload a PDF")
    doc_id = uuid.uuid4().hex[:12]
    dest = _TMP / f"{doc_id}.pdf"
    with dest.open("wb") as fh:
        shutil.copyfileobj(file.file, fh)
    _UPLOADS[doc_id] = dest
    try:
        result = run(str(dest))
    except Exception as exc:                      # fail loud, never a blank grid
        raise HTTPException(500, f"extraction failed: {exc}") from exc
    result["document"]["id"] = doc_id
    result["document"]["original_name"] = file.filename
    _RESULTS[doc_id] = result
    return JSONResponse(result)


@app.get("/api/result/{doc_id}")
def result(doc_id: str) -> JSONResponse:
    if doc_id not in _RESULTS:
        raise HTTPException(404, "unknown document")
    return JSONResponse(_RESULTS[doc_id])


@app.get("/api/page/{doc_id}/{page_no}.png")
def page_png(doc_id: str, page_no: int) -> Response:
    path = _UPLOADS.get(doc_id)
    if path is None:
        raise HTTPException(404, "unknown document")
    return Response(render_page_png(str(path), page_no), media_type="image/png",
                    headers={"X-Render-Scale": str(SCALE)})


@app.get("/api/scale")
def scale() -> dict:
    return {"scale": SCALE}
