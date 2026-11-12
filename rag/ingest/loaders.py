"""B1 loaders: PDF CVs, Markdown case studies, repo READMEs + code, reviews, past proposals.

Reads the on-disk persona layout from docs/INTERFACES.md section 1:

    data/personas/<persona>/{profile.json, cv.md, cv.pdf, case_studies/<pid>.md,
                             repos/<pid>/README.md + src/*, reviews.json, proposals.json,
                             projects.json}

Every Document carries persona, type, project, skills, date, client industry and (proposals)
outcome. Skills are the union of skills detected in the text and the project's fact-sheet skills.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from pathlib import Path

from rag.types import Document

CODE_EXTS = {".py", ".ts", ".tsx", ".js", ".sql", ".go", ".java", ".rb", ".sh", ".r", ".ipynb"}
Summarizer = Callable[[dict, list[Document]], str]


# ----------------------------------------------------------------------------- skills
class SkillVocab:
    """Case-insensitive whole-token matcher for a known skill list."""

    def __init__(self, skills: Iterable[str]):
        self.canonical: dict[str, str] = {}
        for s in skills:
            s = s.strip()
            if s:
                self.canonical.setdefault(s.lower(), s)
        names = sorted(self.canonical, key=len, reverse=True)
        if names:
            alt = "|".join(re.escape(n) for n in names)
            self._re = re.compile(rf"(?<![\w+#])(?:{alt})(?![\w+#])", re.IGNORECASE)
        else:
            self._re = None

    def find(self, text: str) -> list[str]:
        if not self._re:
            return []
        seen: dict[str, None] = {}
        for m in self._re.finditer(text):
            seen[self.canonical[m.group(0).lower()]] = None
        return list(seen)


def _merge_skills(*groups: Iterable[str]) -> list[str]:
    out: dict[str, None] = {}
    for g in groups:
        for s in g:
            out.setdefault(s, None)
    return list(out)


# ----------------------------------------------------------------------------- low level
def read_pdf_text(path: str | Path | bytes) -> str:
    """Extract text from a PDF with pypdf ('' when the PDF has no text layer)."""
    import io

    from pypdf import PdfReader

    src = io.BytesIO(path) if isinstance(path, bytes) else str(path)
    reader = PdfReader(src)
    return "\n\n".join((page.extract_text() or "").strip() for page in reader.pages).strip()


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _read_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(_read(path))


def _md_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#"):
            return line.lstrip("#").strip() or fallback
        if line:
            break
    return fallback


# ----------------------------------------------------------------------------- per-type loaders
def load_cv(persona_dir: Path, persona: str, vocab: SkillVocab) -> list[Document]:
    pdf, md = persona_dir / "cv.pdf", persona_dir / "cv.md"
    text, source = "", ""
    if pdf.exists():
        try:
            text = read_pdf_text(pdf)
            source = "cv.pdf"
        except Exception:  # noqa: BLE001 - corrupt PDF: fall back to the markdown twin
            text = ""
    if not text and md.exists():
        text, source = _read(md), "cv.md"
    if not text:
        return []
    return [Document(doc_id=f"{persona}:cv", persona=persona, type="cv", text=text,
                     title="CV", source=source, skills=vocab.find(text))]


def load_case_studies(persona_dir: Path, persona: str, vocab: SkillVocab,
                      projects: dict[str, dict]) -> list[Document]:
    docs = []
    for path in sorted((persona_dir / "case_studies").glob("*.md")):
        pid = path.stem
        text = _read(path)
        docs.append(_project_doc(persona, "case_study", pid, text, f"case_studies/{path.name}",
                                 _md_title(text, pid), vocab, projects))
    return docs


def load_repos(persona_dir: Path, persona: str, vocab: SkillVocab,
               projects: dict[str, dict]) -> list[Document]:
    docs = []
    for repo in sorted((persona_dir / "repos").glob("*")):
        if not repo.is_dir():
            continue
        pid = repo.name
        for path in sorted(repo.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(persona_dir).as_posix()
            text = _read(path)
            if path.name.lower().startswith("readme"):
                docs.append(_project_doc(persona, "readme", pid, text, rel,
                                         _md_title(text, f"{pid} README"), vocab, projects))
            elif path.suffix.lower() in CODE_EXTS:
                title = f"{projects.get(pid, {}).get('title', pid)} / {path.name}"
                docs.append(_project_doc(persona, "code", pid, text, rel, title, vocab, projects,
                                         doc_key=f"{pid}/{path.relative_to(repo).as_posix()}"))
    return docs


def _project_doc(persona: str, dtype: str, pid: str, text: str, source: str, title: str,
                 vocab: SkillVocab, projects: dict[str, dict], doc_key: str | None = None
                 ) -> Document:
    proj = projects.get(pid, {})
    return Document(
        doc_id=f"{persona}:{dtype}:{doc_key or pid}", persona=persona, type=dtype, text=text,
        title=title, source=source, project_id=pid, project_ids=[pid],
        skills=_merge_skills(proj.get("skills", []), vocab.find(text)),
        date=proj.get("date"), client_industry=proj.get("industry"),
        project_title=proj.get("title", ""),
    )


def load_reviews(persona_dir: Path, persona: str, vocab: SkillVocab,
                 projects: dict[str, dict]) -> list[Document]:
    docs = []
    for rev in _read_json(persona_dir / "reviews.json", []):
        pid = rev.get("project_id")
        proj = projects.get(pid, {})
        text = rev.get("text", "")
        docs.append(Document(
            doc_id=f"{persona}:review:{rev['review_id']}", persona=persona, type="review",
            text=text, title=f"Client review ({rev.get('rating', '?')}/5)",
            source="reviews.json", project_id=pid, project_ids=[pid] if pid else [],
            skills=_merge_skills(proj.get("skills", []), vocab.find(text)),
            date=rev.get("date"), client_industry=rev.get("client_industry"),
            project_title=proj.get("title", ""), extra={"rating": rev.get("rating")}))
    return docs


def load_proposals(persona_dir: Path, persona: str, vocab: SkillVocab,
                   projects: dict[str, dict]) -> list[Document]:
    """Past proposals, outcome-labelled (won | replied | ignored)."""
    docs = []
    for prop in _read_json(persona_dir / "proposals.json", []):
        pids = [p for p in prop.get("project_ids", []) if p]
        text = prop.get("text", "")
        docs.append(Document(
            doc_id=f"{persona}:proposal:{prop['proposal_id']}", persona=persona, type="proposal",
            text=text, title=prop.get("job_title", "Past proposal"), source="proposals.json",
            project_id=pids[0] if pids else None, project_ids=pids,
            skills=_merge_skills(vocab.find(text),
                                 *(projects.get(p, {}).get("skills", []) for p in pids)),
            date=prop.get("date"), client_industry=prop.get("client_industry"),
            outcome=prop.get("outcome"),
            project_title=projects.get(pids[0], {}).get("title", "") if pids else "",
            extra={"category": prop.get("category")}))
    return docs


# ----------------------------------------------------------------------------- summaries (V5)
def default_summarizer(project: dict, docs: list[Document]) -> str:
    """Template summary: title, industry, skills, outcome line and the case-study opening."""
    lead = ""
    for d in docs:
        if d.type == "case_study":
            body = [ln.strip() for ln in d.text.splitlines()
                    if ln.strip() and not ln.strip().startswith("#")]
            lead = " ".join(" ".join(body).split()[:70])
            break
    parts = [f"{project.get('title', project['project_id'])}.",
             f"Industry: {project.get('industry', 'n/a')}.",
             f"Skills: {', '.join(project.get('skills', []))}.",
             project.get("outcome_summary", ""), lead]
    return " ".join(p for p in parts if p)


def build_summary_docs(persona: str, projects: dict[str, dict], docs: list[Document],
                       summarizer: Summarizer | None = None) -> list[Document]:
    summarizer = summarizer or default_summarizer
    by_proj: dict[str, list[Document]] = {}
    for d in docs:
        if d.project_id:
            by_proj.setdefault(d.project_id, []).append(d)
    out = []
    for pid, proj in projects.items():
        text = summarizer(proj, by_proj.get(pid, []))
        out.append(Document(
            doc_id=f"{persona}:summary:{pid}", persona=persona, type="summary", text=text,
            title=f"{proj.get('title', pid)} (summary)", source="projects.json", project_id=pid,
            project_ids=[pid], skills=list(proj.get("skills", [])), date=proj.get("date"),
            client_industry=proj.get("industry"), project_title=proj.get("title", "")))
    return out


# ----------------------------------------------------------------------------- whole persona
def load_projects(persona_dir: Path) -> dict[str, dict]:
    return {p["project_id"]: p for p in _read_json(persona_dir / "projects.json", [])}


def load_persona(persona_dir: str | Path, persona: str | None = None, *,
                 summarizer: Summarizer | None = None, with_summaries: bool = True
                 ) -> list[Document]:
    """Load every document of one persona (the full B1 ingestion pass)."""
    persona_dir = Path(persona_dir)
    persona = persona or persona_dir.name
    projects = load_projects(persona_dir)
    profile = _read_json(persona_dir / "profile.json", {})
    vocab = SkillVocab(_merge_skills(profile.get("skills", []),
                                     *(p.get("skills", []) for p in projects.values())))
    docs = [
        *load_cv(persona_dir, persona, vocab),
        *load_case_studies(persona_dir, persona, vocab, projects),
        *load_repos(persona_dir, persona, vocab, projects),
        *load_reviews(persona_dir, persona, vocab, projects),
        *load_proposals(persona_dir, persona, vocab, projects),
    ]
    if with_summaries and projects:
        docs += build_summary_docs(persona, projects, docs, summarizer)
    return docs
