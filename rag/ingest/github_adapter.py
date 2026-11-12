"""GitHub-MCP ingestion adapter (B1).

The real GitHub MCP server is plugged in by injecting a ``fetch_file(repo, path) -> str | None``
callable (e.g. a thin wrapper over the MCP tool ``get_file_contents``). Optionally inject
``list_files(repo) -> list[str]`` to discover paths; otherwise pass ``paths`` explicitly. Nothing
here imports an MCP client, so the adapter is testable offline with a dict-backed fake::

    docs = ingest_github_repo(
        "me/forecasting-api", fetch_file=lambda repo, path: mcp.call("get_file_contents", ...),
        persona="ai_ml", project_id="p03", paths=["README.md", "src/model.py"],
        project={"title": "Demand forecasting API", "skills": ["Python"], "industry": "retail"})

Documents come back ready for ``PersonaIndex.add_document`` (hash-based incremental update).
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import PurePosixPath

from rag.ingest.loaders import CODE_EXTS, SkillVocab
from rag.types import Document

FetchFile = Callable[[str, str], "str | None"]
ListFiles = Callable[[str], "list[str]"]
MAX_FILE_CHARS = 60_000


def ingest_github_repo(repo: str, *, fetch_file: FetchFile, persona: str, project_id: str,
                       paths: list[str] | None = None, list_files: ListFiles | None = None,
                       project: dict | None = None, skills_vocab: list[str] | None = None,
                       ) -> list[Document]:
    project = project or {}
    if paths is None:
        if list_files is None:
            raise ValueError("pass `paths` or a `list_files` callable")
        paths = list_files(repo)
    vocab = SkillVocab([*project.get("skills", []), *(skills_vocab or [])])
    docs: list[Document] = []
    for path in paths:
        suffix = PurePosixPath(path).suffix.lower()
        name = PurePosixPath(path).name.lower()
        is_readme = name.startswith("readme")
        if not is_readme and suffix not in CODE_EXTS:
            continue
        text = fetch_file(repo, path)
        if not text or not text.strip():
            continue
        text = text[:MAX_FILE_CHARS]
        doc_id = (f"{persona}:readme:{project_id}" if is_readme
                  else f"{persona}:code:{project_id}/{path}")
        docs.append(Document(
            doc_id=doc_id,
            persona=persona, type="readme" if is_readme else "code", text=text,
            title=project.get("title", project_id) + ("" if is_readme else f" / {path}"),
            source=f"github:{repo}/{path}", project_id=project_id, project_ids=[project_id],
            skills=list(dict.fromkeys([*project.get("skills", []), *vocab.find(text)])),
            date=project.get("date"), client_industry=project.get("industry"),
            project_title=project.get("title", "")))
    return docs
