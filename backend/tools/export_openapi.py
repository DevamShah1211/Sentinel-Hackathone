"""
Write the platform's OpenAPI specification to DOCS/api/.

    python tools/export_openapi.py

Generated from the running application's route definitions, so it cannot drift
from the API the way a hand-maintained document does — if an endpoint changes,
re-running this is the whole update.

Why it is committed rather than left at /api/openapi.json: a department
integrating with this platform needs the contract before they have a running
instance to query, and the submission asks for integration-ready APIs as a
deliverable. A URL that only resolves when our server happens to be up is not a
deliverable.

The spec is written without starting a server — FastAPI builds it from the app
object — so this runs in CI or on a machine with no database.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

OUT_DIR = Path(__file__).resolve().parents[2] / "DOCS" / "api"


def main() -> int:
    from main import app

    spec = app.openapi()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    json_path = OUT_DIR / "openapi.json"
    json_path.write_text(json.dumps(spec, indent=2, ensure_ascii=False),
                         encoding="utf-8")

    paths = spec.get("paths", {})
    methods = ("get", "post", "put", "patch", "delete")
    operations = sum(len([m for m in ops if m in methods]) for ops in paths.values())
    schemas = len(spec.get("components", {}).get("schemas", {}))

    print(f"Wrote {json_path.relative_to(OUT_DIR.parents[1])}")
    print(f"  {len(paths)} paths · {operations} operations · {schemas} schemas")

    # A YAML copy as well, when PyYAML is available: most API tooling and every
    # reviewer reading it by eye prefers YAML, and neither should have to
    # convert it themselves.
    try:
        import yaml
    except ImportError:
        print("  (PyYAML not installed — skipped the YAML copy)")
        return 0

    yaml_path = OUT_DIR / "openapi.yaml"
    yaml_path.write_text(
        yaml.safe_dump(spec, sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8")
    print(f"Wrote {yaml_path.relative_to(OUT_DIR.parents[1])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
