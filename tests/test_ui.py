"""M6 gates: the review UI serves the pipeline's own output."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ui.app import app


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def uploaded(client):
    with open("data/protocols/protocol9.pdf", "rb") as fh:
        r = client.post("/api/upload",
                        files={"file": ("protocol9.pdf", fh, "application/pdf")})
    assert r.status_code == 200
    return r.json()


def test_index_serves(client):
    r = client.get("/")
    assert r.status_code == 200 and "SoA Extractor" in r.text


def test_upload_returns_ranked_candidates(uploaded):
    assert len(uploaded["tables"]) >= 2, "candidate list must offer alternatives"
    scores = [t["confidence"] for t in uploaded["tables"]]
    assert scores == sorted(scores, reverse=True), "candidates must be ranked"
    assert "Schedule of Measures" in uploaded["tables"][0]["title_verbatim"]


def test_page_render_endpoint(client, uploaded):
    doc_id = uploaded["document"]["id"]
    r = client.get(f"/api/page/{doc_id}/26.png")
    assert r.status_code == 200
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert float(r.headers["X-Render-Scale"]) > 0


def test_cells_carry_bbox_for_hover(uploaded):
    cells = uploaded["tables"][0]["cells"]
    assert cells and all(len(c["bbox"]) == 4 for c in cells)
    assert all(c.get("page") for c in cells)


def test_unknown_document_is_404(client):
    assert client.get("/api/page/nosuch/1.png").status_code == 404
    assert client.get("/api/result/nosuch").status_code == 404


def test_non_pdf_rejected(client):
    r = client.post("/api/upload", files={"file": ("a.txt", b"hi", "text/plain")})
    assert r.status_code == 400
