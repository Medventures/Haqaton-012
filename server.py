"""PRIME HTTP application, served by Waitress on Windows and Linux."""

from __future__ import annotations

from collections import OrderedDict, deque
import hmac
import json
import logging
import os
from pathlib import Path
import socket
import sys
import threading
import time
from urllib.parse import urlsplit

from flask import Flask, Response, jsonify, request, send_from_directory, stream_with_context
from werkzeug.exceptions import HTTPException

from config import Settings, load_settings
from domain import PROGRAMS, _validate_answers, clarify, recommend


PUBLIC = Path(__file__).resolve().parent / "public"
LOGGER = logging.getLogger("prime.server")


class RateLimiter:
    """Bounded in-process limiter; deploy one instance or add an edge limit."""

    def __init__(self, limit: int, window: int):
        self.limit, self.window = limit, window
        self.entries = OrderedDict()
        self.lock = threading.Lock()

    def allow(self, address: str) -> bool:
        now = time.monotonic()
        with self.lock:
            while self.entries:
                _, oldest = next(iter(self.entries.items()))
                if oldest[-1] > now - self.window and len(self.entries) < 10000:
                    break
                self.entries.popitem(last=False)
            events = self.entries.setdefault(address, deque())
            while events and events[0] <= now - self.window:
                events.popleft()
            self.entries.move_to_end(address)
            if len(events) >= self.limit:
                return False
            events.append(now)
            return True


def create_app(settings: Settings | None = None, agent_service=None, metrics_store=None) -> Flask:
    settings = settings or load_settings()
    app = Flask(__name__, static_folder=None)
    app.json.ensure_ascii = False
    trusted_hosts = sorted({urlsplit(origin).hostname for origin in settings.allowed_origins})
    # Local health probes remain possible behind an HTTPS terminating proxy.
    trusted_hosts.extend(["127.0.0.1", "localhost"])
    app.config.update(MAX_CONTENT_LENGTH=settings.max_body_bytes, TRUSTED_HOSTS=trusted_hosts, PROPAGATE_EXCEPTIONS=False)
    limiter = RateLimiter(settings.rate_limit, settings.rate_window)
    admin_limiter = RateLimiter(30, 60)
    slots = threading.BoundedSemaphore(settings.max_concurrent_agents)
    service_lock = threading.Lock()
    app.extensions["prime_settings"] = settings
    app.extensions["prime_agent_slots"] = slots
    app.extensions["prime_rate_limiter"] = limiter
    app.extensions["prime_agent_service"] = agent_service
    app.extensions["prime_metrics_store"] = metrics_store

    def error(message: str, status: int):
        return jsonify(error=message), status

    @app.before_request
    def protect_request():
        if request.method not in ("GET", "HEAD", "POST"):
            return error("Этот способ запроса не поддерживается.", 405)
        if request.method != "POST":
            return None
        # A forwarded header never grants trust. Configure exact public origins.
        origin = request.headers.get("Origin")
        if origin and origin not in settings.allowed_origins:
            return error("Этот адрес сайта не разрешён.", 403)
        if not origin and request.headers.get("Sec-Fetch-Site") == "cross-site":
            return error("Этот адрес сайта не разрешён.", 403)
        if request.mimetype != "application/json":
            return error("Отправьте ответы в формате JSON.", 415)
        if request.content_length is None:
            return error("Не удалось определить размер запроса.", 411)
        if request.content_length > settings.max_body_bytes:
            return error("Ответ слишком большой. Сократите текст и попробуйте ещё раз.", 413)
        if not limiter.allow(request.remote_addr or "unknown"):
            response = jsonify(error="Слишком много запросов. Подождите минуту и попробуйте ещё раз.")
            response.status_code = 429
            response.headers["Retry-After"] = str(settings.rate_window)
            return response
        return None

    @app.after_request
    def secure_response(response):
        response.headers.update({
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "no-referrer",
            "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; object-src 'none'",
        })
        if settings.environment == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        messages = {400: "Не удалось прочитать запрос. Проверьте ответы и попробуйте ещё раз.", 404: "Страница не найдена.", 405: "Этот способ запроса не поддерживается.", 413: "Ответ слишком большой. Сократите текст и попробуйте ещё раз."}
        return error(messages.get(exc.code, "Не удалось обработать запрос."), exc.code or 500)

    @app.errorhandler(ValueError)
    def handle_validation(exc):
        message = str(exc)
        return error(message if message and not message.isascii() else "Проверьте ответы в анкете.", 400)

    @app.errorhandler(Exception)
    def handle_failure(exc):
        # Never record exception values, request bodies, headers or patient data.
        LOGGER.error("request_failed error_type=%s", type(exc).__name__)
        return error("Не удалось обработать запрос. Попробуйте ещё раз.", 500)

    def read_answers():
        answers = request.get_json()
        _validate_answers(answers)
        return answers

    def get_metrics():
        if app.extensions["prime_metrics_store"] is None:
            with service_lock:
                if app.extensions["prime_metrics_store"] is None:
                    from metrics import MetricsStore
                    app.extensions["prime_metrics_store"] = MetricsStore(settings.metrics_db)
        return app.extensions["prime_metrics_store"]

    @app.get("/healthz")
    def health():
        return jsonify(status="ok")

    @app.get("/readyz")
    def ready():
        try:
            get_metrics().summary()
        except Exception as exc:
            LOGGER.error("readiness_failed error_type=%s", type(exc).__name__)
            return jsonify(status="unavailable", ai_configured=settings.ai_available), 503
        return jsonify(status="ready", ai_configured=settings.ai_available)

    @app.get("/api/config")
    def public_config():
        return jsonify(ai_available=settings.ai_available, disclosure="С вашего согласия ответы анкеты и уточнение будут переданы в OpenAI для работы виртуального ассистента. Не указывайте ФИО, ИИН, телефон или другие данные, по которым вас можно узнать. Ассистент не ставит диагноз. Окончательный план определяет врач.")

    @app.get("/api/catalog")
    def catalog():
        return jsonify(programs=[{"id": key, **value} for key, value in PROGRAMS.items()], price_note="Цены демонстрационные. Итоговую стоимость подтвердит клиника.")

    @app.post("/api/events")
    def track_event():
        get_metrics().track(request.get_json())
        return jsonify(status="ok"), 202

    @app.get("/api/metrics")
    def private_metrics():
        if not admin_limiter.allow(request.remote_addr or "unknown"):
            return error("Слишком много запросов. Попробуйте через минуту.", 429)
        supplied = request.headers.get("Authorization", "")
        expected = "Bearer " + settings.admin_token
        if not settings.admin_token or not hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8")):
            return error("Доступ к статистике ограничен.", 403)
        return jsonify(get_metrics().summary())

    @app.post("/api/clarify")
    def rule_clarify():
        return jsonify(clarify(read_answers()))

    @app.post("/api/recommend")
    def rule_recommend():
        return jsonify(recommend(read_answers()))

    def get_agent():
        if app.extensions["prime_agent_service"] is None:
            with service_lock:
                if app.extensions["prime_agent_service"] is None:
                    from agent_engine import AgentService
                    app.extensions["prime_agent_service"] = AgentService(settings)
        return app.extensions["prime_agent_service"]

    def agent_response(kind):
        answers = read_answers()
        if not isinstance(answers.get("ai_consent", False), bool):
            return error("Проверьте согласие на работу ассистента.", 400)
        if not slots.acquire(blocking=False):
            response = jsonify(error="Сейчас ассистент помогает другим пациентам. Попробуйте через минуту.")
            response.status_code = 429
            response.headers["Retry-After"] = "30"
            return response
        try:
            service = get_agent()
            events = service.clarify_events(answers) if kind == "clarify" else service.recommend_events(answers)
        except Exception:
            slots.release()
            raise
        released = False

        def release_slot():
            nonlocal released
            if not released:
                released = True
                slots.release()

        def generate():
            try:
                for event in events:
                    yield json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n"
            except GeneratorExit:
                raise
            except ValueError as exc:
                message = str(exc)
                yield json.dumps({"type": "error", "message": message if message and not message.isascii() else "Проверьте ответы и попробуйте ещё раз."}, ensure_ascii=False) + "\n"
            except Exception as exc:
                LOGGER.error("agent_failed error_type=%s", type(exc).__name__)
                yield json.dumps({"type": "error", "message": "Не удалось получить ответ ассистента. Попробуйте ещё раз или продолжите без него."}, ensure_ascii=False) + "\n"
            finally:
                try:
                    close = getattr(events, "close", None)
                    if close:
                        close()
                finally:
                    release_slot()

        response = Response(stream_with_context(generate()), content_type="application/x-ndjson; charset=utf-8")
        response.headers["X-Accel-Buffering"] = "no"
        response.call_on_close(release_slot)
        return response

    @app.post("/api/agent/clarify")
    def agent_clarify():
        return agent_response("clarify")

    @app.post("/api/agent/recommend")
    def agent_recommend():
        return agent_response("recommend")

    @app.get("/")
    def index():
        return send_from_directory(PUBLIC, "index.html")

    @app.get("/<path:filename>")
    def asset(filename):
        if any(part.startswith(".") for part in filename.replace("\\", "/").split("/")):
            return error("Страница не найдена.", 404)
        if not (PUBLIC / filename).resolve().is_relative_to(PUBLIC.resolve()):
            return error("Страница не найдена.", 404)
        return send_from_directory(PUBLIC, filename)

    return app


def _bind_listener(host: str, port: int):
    """Keep ownership until shutdown; Windows must never share a listening port."""
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    listener = socket.socket(family, socket.SOCK_STREAM)
    try:
        if os.name == "nt":
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((host, port))
        return listener
    except OSError:
        listener.close()
        raise


def main():
    from waitress.server import create_server
    try:
        settings = load_settings()
    except ValueError as exc:
        print(f"Не удалось запустить сервис: {exc}", file=sys.stderr, flush=True)
        return 1
    try:
        listener = _bind_listener(settings.host, settings.port)
    except OSError:
        print(f"Не удалось занять адрес {settings.host}:{settings.port}: порт занят или недоступен. Остановите предыдущий сервер либо задайте другой MEDHUB_PORT.", file=sys.stderr, flush=True)
        return 1
    with listener:
        application = create_app(settings)
        try:
            server = create_server(application, sockets=[listener], threads=settings.threads,
                max_request_body_size=settings.max_body_bytes, max_request_header_size=16384,
                channel_timeout=240, connection_limit=128, expose_tracebacks=False,
                clear_untrusted_proxy_headers=True, ident="PRIME")
        except (OSError, ValueError):
            print("Не удалось запустить сервер. Проверьте адрес, порт и настройки запуска.", file=sys.stderr, flush=True)
            return 1
        display_host = f"[{settings.host}]" if ":" in settings.host else settings.host
        print(f"Сервис открыт: http://{display_host}:{settings.port}", flush=True)
        try:
            server.run()
        finally:
            server.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
