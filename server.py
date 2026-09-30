"""Russian-language demo API and static server. Python standard library only."""

from __future__ import annotations

import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from domain import DEMO_PROFILES, PRICE_SOURCE, PROGRAMS, get_profile, recommend_from_profile
from storage import (complete_demo_booking, create_booking, get_metrics,
                     get_profile_booking, get_slots, initialize,
                     record_recommendation, save_feedback)


ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"


class Handler(BaseHTTPRequestHandler):
    def send_json(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("Проверьте отправленные данные.") from exc
        if length <= 0 or length > 16384:
            raise ValueError("Проверьте отправленные данные.")
        try:
            data = json.loads(self.rfile.read(length))
        except json.JSONDecodeError as exc:
            raise ValueError("Не удалось прочитать данные. Попробуйте ещё раз.") from exc
        if not isinstance(data, dict):
            raise ValueError("Проверьте отправленные данные.")
        return data

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        try:
            data = self.read_json()
            if path == "/api/recommend":
                profile = get_profile(data.get("profile_id"))
                result = recommend_from_profile(profile)
                if result["status"] == "recommended":
                    record_recommendation(profile["id"], result["checkup_id"])
                self.send_json(result)
            elif path == "/api/bookings":
                profile = get_profile(data.get("profile_id"))
                program_id = data.get("program_id")
                if program_id not in PROGRAMS:
                    raise ValueError("Выбранная программа не найдена.")
                booking = create_booking(profile["id"], program_id, data.get("start_at", ""), bool(profile.get("last_checkup")))
                self.send_json({"booking": booking}, 201)
            elif path == "/api/bookings/complete-demo":
                profile = get_profile(data.get("profile_id"))
                booking_id = data.get("booking_id")
                if not isinstance(booking_id, int) or isinstance(booking_id, bool):
                    raise ValueError("Запись не найдена.")
                self.send_json({"booking": complete_demo_booking(booking_id, profile["id"])})
            elif path == "/api/bookings/feedback":
                profile = get_profile(data.get("profile_id"))
                booking_id = data.get("booking_id")
                if not isinstance(booking_id, int) or isinstance(booking_id, bool):
                    raise ValueError("Запись не найдена.")
                self.send_json({"booking": save_feedback(booking_id, profile["id"], data.get("score"))})
            else:
                self.send_json({"error": "Страница не найдена."}, 404)
        except ValueError as exc:
            self.send_json({"error": str(exc)}, 400)

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        try:
            if path == "/api/catalog":
                self.send_json({"programs": [{"id": key, **value} for key, value in PROGRAMS.items()],
                                "price_source": PRICE_SOURCE, "price_note": "Цены справочные. Точную стоимость подтвердит клиника."})
                return
            if path == "/api/demo-profiles":
                self.send_json({"profiles": [{"id": key, "display_name": value["display_name"]} for key, value in DEMO_PROFILES.items()],
                                "source": "Демонстрационные данные"})
                return
            if path.startswith("/api/demo-profiles/"):
                self.send_json({"profile": get_profile(path.rsplit("/", 1)[-1])})
                return
            if path == "/api/slots":
                self.send_json({"slots": get_slots(query.get("program_id", [""])[0]),
                                "source": "Демонстрационное расписание",
                                "note": "Оценка загрузки основана на демонстрационном календаре. Клиника подтвердит время после подключения своего расписания."})
                return
            if path == "/api/bookings":
                profile = get_profile(query.get("profile_id", [""])[0])
                self.send_json({"booking": get_profile_booking(profile["id"])})
                return
            if path == "/api/metrics":
                self.send_json(get_metrics())
                return
            if path == "/api/status":
                self.send_json({"health_record": "Демонстрационная карта", "calendar": "Демонстрационное расписание",
                                "booking": "Демонстрационная запись", "damumed_connected": False, "clinic_calendar_connected": False})
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
        except ValueError as exc:
            self.send_json({"error": str(exc)}, 400)


if __name__ == "__main__":
    initialize()
    server = ThreadingHTTPServer(("127.0.0.1", 8000), Handler)
    print("Сервис открыт: http://127.0.0.1:8000", flush=True)
    server.serve_forever()
