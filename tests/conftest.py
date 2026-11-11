import pytest


@pytest.fixture(autouse=True)
def _isolated_runtime_dirs(tmp_path, monkeypatch):
    """Traces, dedup store and caches go to a temp dir so tests never see each other's state."""
    import agent.trace as trace
    from agent.nodes import scout as scout_mod

    monkeypatch.setattr(trace, "TRACE_DIR", tmp_path / "traces")
    scout_mod.set_dedup_store(scout_mod.DedupStore(":memory:"))
    yield
