"""Loopback-only disposable HTTPS app for the desktop-worker browser test."""

import json, subprocess, tempfile
from pathlib import Path
import uvicorn
from photoflow_web.app import create_app

with tempfile.TemporaryDirectory(prefix="photoflow-google-worker-") as temporary:
    base = Path(temporary)
    root = base / "library"
    (root / ".photoflow").mkdir(parents=True)
    (root / ".photoflow/library.json").write_text(
        '{"schema_version":2,"library_id":"worker-fixture"}'
    )
    key, cert = base / "key.pem", base / "cert.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=IP:127.0.0.1,DNS:localhost",
        ],
        check=True,
        capture_output=True,
    )
    app = create_app(
        root,
        base / "state",
        auth=lambda d: {
            "ok": d.get("username") == "fixture"
            and (d.get("password") == "fixture-local-only" or d.get("uid") == 12345),
            "uid": 12345,
        },
        role_resolver=lambda n: 3 if n == "fixture" else 0,
    )
    print(json.dumps({"url": "https://127.0.0.1:8099"}), flush=True)
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8099,
        ssl_keyfile=str(key),
        ssl_certfile=str(cert),
        log_level="warning",
        ws_max_size=16384,
    )
