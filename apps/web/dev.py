"""Persistent loopback-only development app, without Linux PAM or real media.

Run from the repo root: .venv/bin/python apps/web/dev.py
Runtime data and a self-signed localhost certificate live in .local/web/.
"""

import json
import os
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "apps/photoflow"))
from photoflow_web.app import create_app
import uvicorn


def main():
    os.umask(0o077)
    base = REPO / ".local/web"
    root = base / "library"
    (root / ".photoflow").mkdir(parents=True, exist_ok=True)
    marker = root / ".photoflow/library.json"
    if not marker.exists():
        marker.write_text(json.dumps({"schema_version": 2, "library_id": "local-development"}))
    elif json.loads(marker.read_text()).get("library_id") != "local-development":
        raise RuntimeError("Refusing to use an unrelated library")
    key, cert = base / "key.pem", base / "cert.pem"
    if not key.exists() or not cert.exists():
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-days", "30", "-keyout", str(key), "-out", str(cert),
            "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost",
            "-addext", "basicConstraints=critical,CA:FALSE",
            "-addext", "keyUsage=critical,digitalSignature,keyEncipherment",
            "-addext", "extendedKeyUsage=serverAuth",
        ], check=True, capture_output=True)

    def authenticate(data):
        return {
            "ok": data.get("username") == "dev" and (
                data.get("password") == "local-development-only" or data.get("uid") == 12345
            ),
            "uid": 12345,
        }

    # Production pilot configuration must not silently enable writes locally.
    os.environ.pop("PHOTOFLOW_GOOGLE_TEST_ACCOUNT", None)
    app = create_app(root, base / "state", auth=authenticate,
                     role_resolver=lambda name: 3 if name == "dev" else 0)
    print("Local PhotoFlow: https://localhost:8099 — dev / local-development-only", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=8099, ssl_keyfile=str(key),
                ssl_certfile=str(cert), ws_max_size=16384, timeout_graceful_shutdown=5)


if __name__ == "__main__":
    main()
