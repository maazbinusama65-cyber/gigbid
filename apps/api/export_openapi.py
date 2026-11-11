"""Write the OpenAPI contract for the web client:  python -m apps.api.export_openapi [out_path]"""
from __future__ import annotations

import json
import sys
from pathlib import Path

DEFAULT_OUT = Path(__file__).resolve().parents[1] / "web" / "openapi.json"


def build_schema() -> dict:
    # Imported lazily and in mock mode so exporting never needs the agent core or a database.
    import os

    os.environ.setdefault("GIGBID_SERVICES", "mock")
    from apps.api.config import AppConfig
    from apps.api.main import create_app

    app = create_app(AppConfig(database_url="sqlite://", services_mode="mock"))
    return app.openapi()


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(build_schema(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
