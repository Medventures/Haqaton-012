"""Browser checks of the clinic dashboard with synthetic API fixtures only.

No environment file or actual token is read. Every /api request is intercepted.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path
import sys
import time
import unittest
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

from browser_smoke import chrome_path


OPTIONS = None
FAKE_TOKEN = "synthetic-dashboard-token-not-a-secret"
CATALOG_NAME = "Программа <img src=x onerror=window.catalogInjected=true>"
DATA = {
    "generated_at": "2026-09-30T10:30:00+00:00",
    "sales": {"booking_intents": 9},
    "time": {"assistant": {"average_ms": 1500, "samples": 12}},
    "repeat_visits": {"reminder_intents": 4},
    "satisfaction": {"average_rating": 4.5, "samples": 8},
    "counts": {"questionnaire_started": 20, "recommendation_ready": 12, "booking_intent": 9, "reminder_intent": 4},
    "packages": [{"package_id": "heart", "recommendations": 12, "booking_intents": 9}],
}


class Fixtures:
    def __init__(self, base_url):
        self.origin = urlsplit(base_url).netloc
        self.data = deepcopy(DATA)
        self.requests = []
        self.hold_next = False
        self.pending = []

    def route(self, route):
        request = route.request
        url = urlsplit(request.url)
        if url.netloc != self.origin:
            route.abort()
        elif url.path == "/api/catalog":
            route.fulfill(json={"programs": [{"id": "heart", "name": CATALOG_NAME}]})
        elif url.path == "/api/metrics":
            self.requests.append(request.headers.get("authorization"))
            if self.hold_next:
                self.hold_next = False
                self.pending.append(route)
            elif request.headers.get("authorization") != "Bearer " + FAKE_TOKEN:
                route.fulfill(status=403, json={"error": "Доступ к статистике ограничен."})
            else:
                route.fulfill(json=self.data)
        elif url.path.startswith("/api/"):
            route.fulfill(status=404, json={"error": "Нет синтетического сценария."})
        else:
            route.continue_()


class MetricsSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(
            executable_path=chrome_path(OPTIONS.chrome), headless=True,
            args=["--disable-gpu", "--disable-gpu-sandbox", "--disable-software-rasterizer", "--disable-features=Vulkan,UseSkiaRenderer", "--disable-extensions", "--disable-background-networking"],
        )

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.context = self.browser.new_context(viewport={"width": 1440, "height": 1100}, locale="ru-RU", reduced_motion="reduce")
        self.fixture = Fixtures(OPTIONS.base_url)
        self.context.route("**/*", self.fixture.route)
        self.page = self.context.new_page()
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.goto(OPTIONS.base_url.rstrip("/") + "/metrics.html", wait_until="networkidle")

    def tearDown(self):
        try:
            self.assertEqual(self.errors, [], "Browser JavaScript errors")
        finally:
            self.context.close()

    def login(self, token=FAKE_TOKEN):
        self.page.locator("#admin-token").fill(token)
        self.page.locator("#metrics-login button").click()

    def screenshot(self, name):
        if OPTIONS.screenshot_dir:
            target = Path(OPTIONS.screenshot_dir)
            target.mkdir(parents=True, exist_ok=True)
            self.page.screenshot(path=str(target / ("fixture-metrics-" + name + ".png")), full_page=True)

    def test_invalid_token_shows_russian_error_and_does_not_open_data(self):
        self.login("synthetic-invalid-token")
        expect(self.page.locator("#metrics-error")).to_have_text("Доступ к статистике ограничен.")
        expect(self.page.locator("#metrics-content")).to_be_hidden()
        expect(self.page.locator("#metrics-login")).to_be_visible()
        expect(self.page.locator("#admin-token")).to_have_value("")

    def test_valid_login_has_four_metrics_and_escapes_catalog(self):
        self.login()
        expect(self.page.locator(".metric-card")).to_have_count(4)
        expect(self.page.locator(".metric-card > strong")).to_have_text(["9", "1,5 с", "4", "4,5 / 5"])
        expect(self.page.locator("#metrics-packages tbody td").first).to_have_text(CATALOG_NAME)
        expect(self.page.locator("#metrics-packages img")).to_have_count(0)
        self.assertFalse(self.page.evaluate("Boolean(window.catalogInjected)"))
        self.assertEqual(self.fixture.requests, ["Bearer " + FAKE_TOKEN])
        self.assertFalse(self.page.evaluate("Object.values(sessionStorage).concat(Object.values(localStorage)).some(value => value.includes('synthetic-dashboard-token'))"))
        self.screenshot("desktop")

    def test_empty_summary_shows_absence_of_samples(self):
        self.fixture.data.update(sales={"booking_intents": 0}, time={"assistant": {"average_ms": None, "samples": 0}}, repeat_visits={"reminder_intents": 0}, satisfaction={"average_rating": None, "samples": 0}, packages=[])
        self.fixture.data["counts"] = {key: 0 for key in self.fixture.data["counts"]}
        self.login()
        expect(self.page.locator(".metric-card > strong")).to_have_text(["0", "—", "0", "—"])
        expect(self.page.locator("#metrics-packages")).to_contain_text("после первых полученных рекомендаций")
        expect(self.page.locator(".funnel-row progress")).to_have_count(4)
        self.assertEqual(self.page.locator(".funnel-row progress").evaluate_all("nodes => nodes.map(node => node.value)"), [0, 0, 0, 0])
        self.screenshot("empty")

    def test_refresh_and_logout_clear_metrics(self):
        self.login()
        expect(self.page.locator("#metrics-content")).to_be_visible()
        self.fixture.data["sales"]["booking_intents"] = 10
        self.page.locator("#metrics-refresh").click()
        expect(self.page.locator(".metric-card > strong").first).to_have_text("10")
        self.page.locator("#metrics-logout").click()
        expect(self.page.locator("#metrics-content")).to_be_hidden()
        expect(self.page.locator("#metrics-login")).to_be_visible()
        expect(self.page.locator("#metrics-cards")).to_be_empty()
        expect(self.page.locator("#metrics-funnel")).to_be_empty()
        expect(self.page.locator("#metrics-packages")).to_be_empty()
        expect(self.page.locator("#metrics-updated")).to_be_empty()
        expect(self.page.locator("#admin-token")).to_be_focused()

    def test_logout_while_refresh_pending_cannot_restore_statistics(self):
        self.login()
        expect(self.page.locator("#metrics-content")).to_be_visible()
        self.fixture.hold_next = True
        self.page.locator("#metrics-refresh").click()
        deadline = time.monotonic() + 3
        while not self.fixture.pending and time.monotonic() < deadline:
            self.page.wait_for_timeout(20)
        self.assertTrue(self.fixture.pending, "Expected a pending intercepted metrics request")
        self.page.locator("#metrics-logout").click()
        for route in self.fixture.pending:
            route.fulfill(json=self.fixture.data)
        self.page.wait_for_timeout(150)
        expect(self.page.locator("#metrics-content")).to_be_hidden()
        expect(self.page.locator("#metrics-cards")).to_be_empty()
        expect(self.page.locator("#metrics-login")).to_be_visible()

    def test_mobile_390_has_no_horizontal_overflow(self):
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.login()
        expect(self.page.locator(".metric-card")).to_have_count(4)
        self.screenshot("mobile")
        dimensions = self.page.evaluate("({viewport: innerWidth, document: document.documentElement.scrollWidth, body: document.body.scrollWidth})")
        self.assertLessEqual(dimensions["document"], dimensions["viewport"])
        self.assertLessEqual(dimensions["body"], dimensions["viewport"])


def main():
    global OPTIONS
    parser = argparse.ArgumentParser(description="Проверка панели на вымышленных данных, без чтения секретов.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--chrome")
    parser.add_argument("--screenshot-dir")
    OPTIONS = parser.parse_args()
    unittest.main(argv=[sys.argv[0]], verbosity=2)


if __name__ == "__main__":
    main()
