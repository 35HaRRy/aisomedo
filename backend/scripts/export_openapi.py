"""Export the FastAPI OpenAPI contract to backend/openapi.json (issue #24).

Run: ``uv run --project backend python backend/scripts/export_openapi.py``
 regroups nothing at runtime; the production app keeps docs/openapi URLs
disabled and this file is the shared contract instead.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from backend.main import create_app  # noqa: E402


def main() -> None:
    app = create_app()
    schema = app.openapi()
    target = ROOT / "openapi.json"
    target.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {target} ({len(schema.get('paths', {}))} paths)")


if __name__ == "__main__":
    main()
