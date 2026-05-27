#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "== Frontend build =="
(cd "$ROOT_DIR/desktop" && npm run build)

echo "== Backend compile =="
(cd "$ROOT_DIR/server" && .venv/bin/python -m compileall app)

echo "== API smoke =="
(cd "$ROOT_DIR/server" && .venv/bin/python - <<'PY'
from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)
checks = [
    ("GET", "/openapi.json", None),
    ("GET", "/api/health", None),
    ("GET", "/api/projects", None),
    ("GET", "/api/settings", None),
    ("POST", "/api/settings/test", {"target": "tts"}),
]

for method, path, body in checks:
    request = getattr(client, method.lower())
    response = request(path, json=body) if body is not None else request(path)
    print(f"{method} {path} {response.status_code}")
    if response.status_code >= 400:
        raise SystemExit(response.text)
PY
)

echo "V1 smoke passed."
