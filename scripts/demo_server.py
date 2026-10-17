"""Local demo viewer for the real CLI. Run: uv run python scripts/demo_server.py."""

import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = {
    "running": False,
    "log": "Ready. Click Run agent to make real Gemini requests.",
    "brief": "",
    "run_dir": "",
}
LOCK = threading.Lock()


def execute():
    command = [
        str(ROOT / ".venv/bin/research"),
        "run",
        "--ticker",
        "SRVCABLE",
        "--company",
        "Sarvottam Cables Ltd",
        "--docs",
        str(ROOT / "research_pack"),
        "--as-of",
        "2026-09-23",
        "--project-dir",
        str(ROOT),
        "--writer-version",
        "writer_v4",
        "--output-root",
        str(ROOT / "artifacts/demo"),
    ]
    try:
        process = subprocess.Popen(
            command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        for line in process.stdout:
            with LOCK:
                STATE["log"] += line
                if "PASS  Research brief: " in line:
                    path = Path(line.split("PASS  Research brief: ", 1)[1].strip())
                    STATE["brief"] = path.read_text()
                    STATE["run_dir"] = str(path.parent)
        code = process.wait()
        with LOCK:
            STATE["log"] += f"\nProcess exit code: {code}\n"
    finally:
        with LOCK:
            STATE["running"] = False


HTML = (Path(__file__).with_name("demo.html")).read_text()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/status":
            with LOCK:
                payload = json.dumps(STATE).encode()
            kind = "application/json"
        elif self.path == "/record":
            payload, kind = (ROOT / "scripts/record.html").read_bytes(), "text/html; charset=utf-8"
        elif self.path == "/":
            payload, kind = HTML.encode(), "text/html; charset=utf-8"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        if self.path == "/save-video" and self.headers.get("Origin") == "http://127.0.0.1:8765":
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size < 100_000_000:
                self.send_error(413)
                return
            target = ROOT / "submission/demo.webm"
            target.write_bytes(self.rfile.read(size))
            self.send_response(201)
            self.end_headers()
            return
        if self.path != "/start" or self.headers.get("Origin") != "http://127.0.0.1:8765":
            self.send_error(403)
            return
        with LOCK:
            if STATE["running"]:
                self.send_error(409)
                return
            STATE.update(running=True, log="Starting real research run...\n", brief="", run_dir="")
        threading.Thread(target=execute, daemon=True).start()
        self.send_response(202)
        self.end_headers()

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print("Demo viewer: http://127.0.0.1:8765", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 8765), Handler).serve_forever()
