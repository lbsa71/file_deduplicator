"""Loopback-only disposable HTTPS app for the desktop-worker browser test."""

import json, os, subprocess, tempfile
from pathlib import Path
import uvicorn
import io, zipfile
from PIL import Image
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
    original = io.BytesIO()
    Image.new("RGB", (3, 2), "red").save(original, "JPEG")
    original = original.getvalue()
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
        output.writestr("photoflow-test-fixture.jpg", original)
    archive = archive.getvalue()
    def fetch_original(url):
        if url != "https://photos.google.com/download/fixture":
            raise ValueError("Unexpected synthetic original URL")
        return archive, "application/zip"
    app.state.google_originals.fetch = fetch_original
    @app.get("/fixture-original-info")
    def original_info():
        return {"size": len(original)}
    app.router.routes.insert(0, app.router.routes.pop())
    port = int(os.environ.get("PHOTOFLOW_WORKER_FIXTURE_PORT", "8100"))
    print(json.dumps({"url": f"https://127.0.0.1:{port}"}), flush=True)
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=port,
        ssl_keyfile=str(key),
        ssl_certfile=str(cert),
        log_level="warning",
        ws_max_size=16384,
    )
