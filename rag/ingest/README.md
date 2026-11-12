# Ingestion (B1)

* `loaders.py` - `load_persona(dir)` reads `cv.pdf` (pypdf; falls back to `cv.md` if the PDF has no
  text layer), `case_studies/*.md`, `repos/<project>/README.md` + code, `reviews.json`,
  `proposals.json` (outcome-labelled) and builds one `summary` document per project (V5).
  Every `Document` carries persona, type, project(s), skills, date, client industry and outcome.
* `chunkers.py` - `fixed_chunks` (V0, 90 words / 20 overlap) and `structure_chunks` (markdown on
  headings with the heading chain kept, code on top-level definitions with the file path kept,
  reviews/proposals whole).
* `github_adapter.py` - `ingest_github_repo(repo, fetch_file=..., persona=..., project_id=...)`.
  The real GitHub MCP server is plugged in by passing `fetch_file(repo, path) -> str | None` (a
  thin wrapper over its file-contents tool) and optionally `list_files(repo)`. Nothing here imports
  an MCP client, so it is unit-tested with a dict-backed fake.
* Incremental re-indexing: `PersonaIndex.add_document(doc)` hashes content plus metadata; an
  unchanged document costs nothing, a changed or new one re-chunks and re-embeds only itself.
  `rag.retriever.add_document(portfolio_id, doc)` does this and persists to
  `data/processed/index/<persona>/` (numpy `.npy` embeddings + JSON metadata).
* Why a tiny numpy index behind `View` instead of Chroma/Qdrant: a persona is ~1k chunks, so exact
  brute-force cosine is sub-millisecond, exact (no ANN recall loss) and needs no service in CI, the
  evals or Docker. A vector-store adapter only has to reimplement `rag/index/store.py::View`.
