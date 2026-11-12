"""Ingestion: loaders, chunkers and the GitHub-MCP adapter (see README.md)."""
from rag.ingest.chunkers import chunk_document, fixed_chunks, structure_chunks
from rag.ingest.github_adapter import ingest_github_repo
from rag.ingest.loaders import SkillVocab, load_persona, read_pdf_text

__all__ = ["chunk_document", "fixed_chunks", "structure_chunks", "ingest_github_repo",
           "SkillVocab", "load_persona", "read_pdf_text"]
