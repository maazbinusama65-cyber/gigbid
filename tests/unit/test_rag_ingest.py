"""B1: loaders, chunkers, metadata, incremental re-indexing, GitHub adapter, persistence."""
from __future__ import annotations

import numpy as np
import pytest

from rag.embedder import HashEmbedder
from rag.index.store import PersonaIndex
from rag.ingest import fixed_chunks, ingest_github_repo, read_pdf_text, structure_chunks
from rag.ingest.chunkers import code_chunks, markdown_chunks
from rag.types import Document
from tests.unit.test_rag_kit import FIXTURE, fixture_docs, fixture_index


def minimal_pdf(text: str) -> bytes:
    """Hand-built one-page PDF with a text layer (so pypdf can be tested offline)."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF" % (len(objs) + 1, xref)
    return out


def test_pdf_cv_text_extraction():
    assert "Prophet forecasting engineer" in read_pdf_text(minimal_pdf("Prophet forecasting engineer"))


def test_every_document_type_loaded_with_metadata():
    docs = fixture_docs()
    types = {d.type for d in docs}
    assert types == {"cv", "case_study", "readme", "code", "review", "proposal", "summary"}
    cs = next(d for d in docs if d.type == "case_study" and d.project_id == "p01")
    assert cs.persona == "ai_ml" and cs.client_industry == "retail" and cs.date == "2023-04-10"
    assert "Prophet" in cs.skills and cs.title == "Demand forecasting API"
    won = next(d for d in docs if d.doc_id.endswith("proposal:pr1"))
    assert won.outcome == "won" and won.project_ids == ["p01"] and won.client_industry == "retail"
    code = next(d for d in docs if d.type == "code" and d.project_id == "p05")
    assert "Celery" in code.skills and code.source.endswith("tasks.py")


def test_fixed_chunks_overlap_and_cover():
    text = " ".join(f"w{i}" for i in range(250))
    chunks = fixed_chunks(text, size=100, overlap=20)
    assert [len(c["text"].split()) for c in chunks][:2] == [100, 100]
    assert chunks[0]["text"].split()[80] == chunks[1]["text"].split()[0]
    assert "w249" in chunks[-1]["text"]
    with pytest.raises(ValueError):
        fixed_chunks("a b c", size=5, overlap=5)


def test_markdown_chunks_keep_heading_chain():
    md = "# Title\n\n## Problem\n" + "word " * 40 + "\n\n## Solution\n" + "term " * 40
    chunks = markdown_chunks(md, "Title")
    assert len(chunks) == 2
    assert chunks[0]["heading"] == "Title > Problem" and chunks[1]["text"].startswith("Title > Solution")


def test_code_chunks_split_on_definitions_and_keep_path():
    src = "import os\n\ndef a():\n    return 1\n\ndef b():\n    return 2\n"
    chunks = code_chunks(src, "src/x.py", max_words=5)
    assert len(chunks) >= 2 and all(c["text"].startswith("# file: src/x.py") for c in chunks)


def test_structure_chunks_keep_review_whole():
    doc = Document(doc_id="d", persona="p", type="review", text="Great work, delivered early.")
    assert structure_chunks(doc)[0]["text"] == "Great work, delivered early."


def test_incremental_reindex_embeds_only_changed_document():
    class Counting(HashEmbedder):
        calls = 0

        def encode(self, texts, *, is_query=False):
            type(self).calls += len(texts)
            return super().encode(texts, is_query=is_query)

    idx = PersonaIndex("ai_ml", Counting())
    docs = list(fixture_docs())
    first = idx.add_documents(docs)
    assert first["added"] == len(docs)
    full_cost = Counting.calls
    assert idx.add_documents(docs)["unchanged"] == len(docs) and Counting.calls == full_cost
    changed = Document(**{**docs[1].__dict__, "text": docs[1].text + " Added Kubernetes work."})
    assert idx.add_document(changed) == "updated"
    assert 0 < Counting.calls - full_cost < full_cost / 5
    new = Document(doc_id="ai_ml:case_study:p99", persona="ai_ml", type="case_study",
                   text="# New work\nBuilt a Kafka stream processor for a logistics client " * 3,
                   title="New work", project_id="p99", project_ids=["p99"], skills=["Kafka"])
    assert idx.add_document(new) == "added"
    assert any(r["project_id"] == "p99" for r in idx.view("struct").records)
    assert idx.remove_document("ai_ml:case_study:p99")
    assert not any(r["project_id"] == "p99" for r in idx.view("struct").records)


def test_metadata_edit_triggers_reindex():
    idx = fixture_index()
    doc = next(d for d in fixture_docs() if d.type == "review")
    edited = Document(**{**doc.__dict__, "client_industry": "healthcare"})
    assert idx.add_document(edited) == "updated"


def test_persistence_roundtrip(tmp_path):
    idx = fixture_index(tmp_path)
    idx.save()
    loaded = PersonaIndex.load("ai_ml", HashEmbedder(), tmp_path)
    assert loaded.stats()["struct_chunks"] == idx.stats()["struct_chunks"]
    q = HashEmbedder().encode(["celery redis"], is_query=True)[0]
    assert loaded.view("ctx").dense(q, 3) == idx.view("ctx").dense(q, 3)
    assert np.allclose(loaded.view("fixed").emb, idx.view("fixed").emb)
    # an index built with another embedder is not reused
    assert PersonaIndex.load("ai_ml", HashEmbedder(dim=64), tmp_path).stats()["docs"] == 0


def test_filters():
    view = fixture_index().view("struct")
    mask = view.mask({"type": "proposal", "outcome": "won"})
    assert {view.records[i]["outcome"] for i in np.flatnonzero(mask)} == {"won"}
    mask = view.mask({"skills": ["celery"]})
    assert all("Celery" in view.records[i]["skills"] for i in np.flatnonzero(mask))
    mask = view.mask({"project_id": "p01", "type": ["case_study", "readme"]})
    assert {view.records[i]["type"] for i in np.flatnonzero(mask)} <= {"case_study", "readme"}


def test_github_adapter_with_injected_fetcher():
    files = {"README.md": "# Repo\nStreaming Kafka consumer.", "src/app.py": "def run():\n    pass\n",
             "logo.png": "binary"}
    calls = []

    def fetch(repo, path):
        calls.append((repo, path))
        return files.get(path)

    docs = ingest_github_repo("me/repo", fetch_file=fetch, persona="ai_ml", project_id="p10",
                              paths=list(files), project={"title": "Kafka app", "skills": ["Kafka"]})
    assert {d.type for d in docs} == {"readme", "code"} and ("me/repo", "logo.png") not in calls
    assert docs[0].source == "github:me/repo/README.md" and "Kafka" in docs[0].skills
    with pytest.raises(ValueError):
        ingest_github_repo("me/repo", fetch_file=fetch, persona="ai_ml", project_id="p10")
    assert FIXTURE.exists()
