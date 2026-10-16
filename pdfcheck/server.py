"""Local browser UI. Files are checked on this machine and are not uploaded anywhere."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from urllib.parse import unquote, urlparse

from pdfcheck.checker import check_pdf

PAGE = (Path(__file__).resolve().parent / "static" / "index.html").read_text(encoding="utf-8")
MAX_BYTES = 25 * 1024 * 1024


def serve(rules: dict[str, Any], host: str = "127.0.0.1", port: int = 8765) -> None:
    server = make_server(rules, host, port)
    print(f"PDF Metadata & Compliance Checker at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


def make_server(rules: dict[str, Any], host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    handler = _handler_factory(rules)
    return ThreadingHTTPServer((host, port), handler)


def _handler_factory(rules: dict[str, Any]) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path in {"/", "/index.html"}:
                body = PAGE.encode("utf-8")
                self._send(200, "text/html; charset=utf-8", body)
                return
            if path == "/api/rules":
                self._send(200, "application/json; charset=utf-8", _json_bytes(rules))
                return
            self._send(404, "text/plain; charset=utf-8", b"Not found")

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path != "/api/check":
                self._send(404, "application/json; charset=utf-8", _json_bytes({"error": "Not found"}))
                return
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length <= 0 or length > MAX_BYTES:
                self._send(
                    400,
                    "application/json; charset=utf-8",
                    _json_bytes({"error": "Send one PDF of 25 MB or less."}),
                )
                return
            data = self.rfile.read(length)
            file_name = _safe_name(self.headers.get("X-Filename", "upload.pdf"))
            with NamedTemporaryFile(suffix=".pdf") as handle:
                handle.write(data)
                handle.flush()
                result = check_pdf(Path(handle.name), rules, display_name=file_name)
            self._send(200, "application/json; charset=utf-8", _json_bytes(result.to_dict()))

        def log_message(self, fmt: str, *args: Any) -> None:
            return

        def _send(self, status: int, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    return Handler


def _safe_name(raw: str) -> str:
    name = unquote(raw or "").replace("\\", "/").split("/")[-1].strip()
    name = name.replace("\r", "").replace("\n", "")
    return name or "upload.pdf"


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload).encode("utf-8")
