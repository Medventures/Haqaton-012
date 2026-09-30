from dataclasses import replace
import errno
import io
import json
import socket
from unittest import TestCase, main
from unittest.mock import MagicMock, patch

from config import Settings
from metrics import MetricsStore
from server import create_app
from server import _bind_listener, main as server_main


ANSWERS = {"age": 35, "sex": "male", "patient_type": "adult", "concerns": ["fatigue"], "family": [], "ai_consent": True}


class FakeAgent:
    def __init__(self):
        self.calls = []

    def clarify_events(self, answers):
        self.calls.append(("clarify", answers))
        yield {"type": "stage", "id": "read", "title": "Читаю анкету", "detail": "", "state": "done"}
        yield {"type": "result", "data": {"status": "question", "question": "Что хотите уточнить?"}}

    def recommend_events(self, answers):
        self.calls.append(("recommend", answers))
        yield {"type": "result", "data": {"status": "recommended"}}


class ServerTests(TestCase):
    def setUp(self):
        self.service = FakeAgent()
        self.store = MetricsStore(":memory:")
        self.settings = Settings(api_key="private-fake-key", signing_secret="private-fake-signing-secret", environment="test", rate_limit=100)
        self.app = create_app(self.settings, self.service, self.store)
        self.client = self.app.test_client()

    def tearDown(self):
        self.store.close()

    def test_health_config_and_headers_do_not_disclose_secrets(self):
        for path in ("/healthz", "/readyz", "/api/config", "/api/catalog", "/"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertNotIn(b"private-fake", response.data)
                self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
                self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                response.close()
        self.assertTrue(self.client.get("/api/config").json["ai_available"])

    def test_readiness_detects_storage_failure_without_error_detail(self):
        class BrokenStore:
            def summary(self):
                raise OSError("private path and key")
        client = create_app(self.settings, self.service, BrokenStore()).test_client()
        response = client.get("/readyz")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(b"private path", response.data)
        self.assertEqual(client.get("/healthz").status_code, 200)

    def test_private_files_and_traversal_are_never_served(self):
        for path in ("/.env", "/.env.example", "/server.py", "/../.env", "/%2e%2e/.env", "/%2e%2e%5c.env", "/.git/config", "/data/metrics.sqlite3"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)

    def test_invalid_json_content_type_size_and_fields_block_agent(self):
        cases = [
            ({"data": "{" , "content_type": "application/json"}, 400),
            ({"data": "{}", "content_type": "text/plain"}, 415),
            ({"data": "x" * 32769, "content_type": "application/json"}, 413),
            ({"json": []}, 400),
            ({"json": {**ANSWERS, "age": 3}}, 400),
            ({"json": {**ANSWERS, "ai_consent": "true"}}, 400),
        ]
        for params, status in cases:
            with self.subTest(status=status, params=str(params)[:50]):
                self.assertEqual(self.client.post("/api/agent/clarify", **params).status_code, status)
        self.assertEqual(self.service.calls, [])

    def test_origin_host_and_forwarded_headers_do_not_grant_trust(self):
        self.assertEqual(self.client.post("/api/clarify", json=ANSWERS, headers={"Origin": "https://attacker.example"}).status_code, 403)
        self.assertEqual(self.client.post("/api/clarify", json=ANSWERS, headers={"Origin": "null"}).status_code, 403)
        self.assertEqual(self.client.post("/api/clarify", json=ANSWERS, headers={"Sec-Fetch-Site": "cross-site"}).status_code, 403)
        self.assertEqual(self.client.get("/", headers={"Host": "attacker.example", "X-Forwarded-Host": "localhost"}).status_code, 400)
        self.assertEqual(self.client.post("/api/clarify", json=ANSWERS, headers={"Origin": "http://localhost:8000"}).status_code, 200)

    def test_existing_rules_routes_and_streaming_agent_contract(self):
        self.assertEqual(self.client.post("/api/clarify", json=ANSWERS).json["status"], "question")
        self.assertEqual(self.client.post("/api/recommend", json=ANSWERS).json["status"], "recommended")
        response = self.client.post("/api/agent/clarify", json=ANSWERS)
        self.assertEqual(response.mimetype, "application/x-ndjson")
        self.assertEqual(response.headers["X-Accel-Buffering"], "no")
        events = [json.loads(line) for line in response.data.splitlines()]
        self.assertEqual([event["type"] for event in events], ["stage", "result"])
        self.assertEqual(events[-1]["data"]["status"], "question")
        self.assertEqual(len(self.service.calls), 1)
        response.close()

    def test_no_consent_is_allowed_for_engine_local_fallback(self):
        app = create_app(replace(self.settings, api_key=""), self.service, self.store)
        with app.test_client().post("/api/agent/clarify", json={**ANSWERS, "ai_consent": False}) as response:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(json.loads(response.data.splitlines()[-1])["type"], "result")
        self.assertFalse(self.service.calls[-1][1]["ai_consent"])

    def test_concurrency_slot_released_when_client_disconnects(self):
        app = create_app(replace(self.settings, max_concurrent_agents=1), self.service, self.store)
        client = app.test_client()
        first = client.post("/api/agent/clarify", json=ANSWERS, buffered=False)
        second = client.post("/api/agent/clarify", json=ANSWERS)
        self.assertEqual(second.status_code, 429)
        first.close()
        with client.post("/api/agent/clarify", json=ANSWERS) as third:
            self.assertEqual(third.status_code, 200)
            third.get_data()

    def test_rate_limit_uses_peer_ip_not_forwarded_ip(self):
        app = create_app(replace(self.settings, rate_limit=1), self.service, self.store)
        client = app.test_client()
        self.assertEqual(client.post("/api/clarify", json=ANSWERS, headers={"X-Forwarded-For": "1.2.3.4"}).status_code, 200)
        response = client.post("/api/clarify", json=ANSWERS, headers={"X-Forwarded-For": "9.8.7.6"})
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["Retry-After"], "60")
        self.assertEqual(client.post("/api/clarify", json=ANSWERS, environ_base={"REMOTE_ADDR": "127.0.0.2"}).status_code, 200)

    def test_metrics_auth_and_payload_privacy(self):
        self.assertEqual(self.client.get("/api/metrics").status_code, 403)
        self.assertEqual(self.client.post("/api/events", json={"event": "questionnaire_started", "mode": "adult", "notes": "private text"}).status_code, 400)
        self.assertEqual(self.client.post("/api/events", json={"event": "questionnaire_started", "mode": "adult"}).status_code, 202)
        app = create_app(replace(self.settings, admin_token="unit-test-admin-token"), self.service, self.store)
        client = app.test_client()
        self.assertEqual(client.get("/api/metrics", headers={"Authorization": "Bearer wrong"}).status_code, 403)
        response = client.get("/api/metrics", headers={"Authorization": "Bearer unit-test-admin-token"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("private text", response.get_data(as_text=True))
        self.assertEqual(response.json["counts"]["questionnaire_started"], 1)

    def test_stream_errors_are_russian_and_do_not_echo_private_exception(self):
        class BrokenAgent:
            def clarify_events(self, answers):
                yield {"type": "stage", "title": "Читаю анкету"}
                raise RuntimeError("private-fake-key and patient notes")
        app = create_app(self.settings, BrokenAgent(), self.store)
        with app.test_client().post("/api/agent/clarify", json=ANSWERS) as response:
            data = response.get_data(as_text=True)
            self.assertNotIn("private-fake", data)
            self.assertEqual(json.loads(data.splitlines()[-1])["type"], "error")
        self.assertTrue(app.extensions["prime_agent_slots"].acquire(blocking=False))


class StartupTests(TestCase):
    def test_windows_socket_is_exclusive_before_binding(self):
        listener = MagicMock()
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", -5)
        with patch("server.socket.socket", return_value=listener), patch("server.os.name", "nt"), patch("server.socket.SO_EXCLUSIVEADDRUSE", exclusive, create=True):
            self.assertIs(_bind_listener("127.0.0.1", 8000), listener)
        self.assertEqual(listener.method_calls[0].args, (socket.SOL_SOCKET, exclusive, 1))
        listener.bind.assert_called_once_with(("127.0.0.1", 8000))
        listener.close.assert_not_called()

    def test_busy_socket_stops_startup_without_ready_message_or_traceback(self):
        listener = MagicMock()
        listener.bind.side_effect = OSError(errno.EADDRINUSE, "private OS error")
        output, errors = io.StringIO(), io.StringIO()
        with patch("server.socket.socket", return_value=listener), patch("server.load_settings", return_value=Settings()), patch("waitress.server.create_server") as factory, patch("server.sys.stdout", output), patch("server.sys.stderr", errors):
            self.assertEqual(server_main(), 1)
        listener.close.assert_called_once()
        factory.assert_not_called()
        self.assertNotIn("Сервис открыт", output.getvalue())
        self.assertIn("порт занят", errors.getvalue())
        self.assertIn("MEDHUB_PORT", errors.getvalue())
        self.assertNotIn("private OS error", errors.getvalue())
        self.assertNotIn("Traceback", errors.getvalue())

    def test_waitress_receives_owned_socket_and_ready_message_follows_listen(self):
        listener, server = MagicMock(), MagicMock()
        output = io.StringIO()

        def build(application, **kwargs):
            self.assertEqual(output.getvalue(), "")
            self.assertEqual(kwargs["sockets"], [listener])
            self.assertNotIn("host", kwargs)
            self.assertNotIn("port", kwargs)
            return server

        with patch("server.load_settings", return_value=Settings()), patch("server._bind_listener", return_value=listener), patch("server.create_app", return_value=object()), patch("waitress.server.create_server", side_effect=build), patch("server.sys.stdout", output):
            self.assertEqual(server_main(), 0)
        self.assertIn("Сервис открыт", output.getvalue())
        server.run.assert_called_once()
        server.close.assert_called_once()


if __name__ == "__main__":
    main()
