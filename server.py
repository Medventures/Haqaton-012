"""Dependency-free web server for the Russian-language check-up MVP."""

from __future__ import annotations

import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from domain import PROGRAMS, recommend


PUBLIC = Path(__file__).resolve().parent / "public"


class Handler(BaseHTTPRequestHandler):
    def send_json(self, value: dict, status: int = 200) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if urlsplit(self.path).path != "/api/recommend":
            self.send_json({"error": "Страница не найдена."}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 2 or length > 16384:
                raise ValueError("Проверьте ответы в анкете.")
            try:
                answers = json.loads(self.rfile.read(length))
            except json.JSONDecodeError as exc:
                raise ValueError("Не удалось прочитать ответы. Попробуйте ещё раз.") from exc
            self.send_json(recommend(answers))
        except ValueError as exc:
            message = str(exc)
            if message.isascii():
                message = "Проверьте ответы в анкете."
            self.send_json({"error": message}, 400)

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/api/catalog":
            self.send_json({"programs": [{"id": key, **value} for key, value in PROGRAMS.items()], "price_note": "Цены демонстрационные. Итоговую стоимость подтвердит клиника."})
            return
        if path == "/":
            path = "/index.html"
        file_path = (PUBLIC / path.lstrip("/")).resolve()
        if not file_path.is_relative_to(PUBLIC) or not file_path.is_file():
            self.send_json({"error": "Страница не найдена."}, 404)
            return
        body = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", (mimetypes.guess_type(file_path)[0] or "application/octet-stream") + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    port = int(os.environ.get("MEDHUB_PORT", "8000"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Сервис открыт: http://127.0.0.1:{port}", flush=True)
    server.serve_forever()
