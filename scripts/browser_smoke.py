"""UI contract smoke tests with synthetic NDJSON fixtures, never a provider evaluation.

Start the app separately, then run:
  python scripts/browser_smoke.py --base-url http://127.0.0.1:8000
No .env file or API key is read. All /api requests are intercepted. The fixture
whose mode is "live" tests that UI state only; it makes no claim about real AI.
Uses existing Chrome/Chromium through --chrome or CHROME_PATH, no browser download.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import shutil
import sys
import unittest
from urllib.parse import urlsplit

from playwright.sync_api import Error as PlaywrightError, expect, sync_playwright

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from domain import recommend  # noqa: E402 -- pure local fixtures, no configuration/secrets


OPTIONS = None
CUSTOM_REPLY = "После ночной смены устаю сильнее, после выходных становится легче."
BEFORE = "Обсудить усталость и привычный режим дня."
AFTER = "На первой консультации обсудить связь усталости с ночными сменами."


def chrome_path(explicit):
    if explicit:
        candidate = Path(explicit)
        if not candidate.is_file():
            raise ValueError("Chrome не найден по указанному пути.")
        return str(candidate)
    candidates = [
        os.environ.get("CHROME_PATH", ""),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        shutil.which("google-chrome"), shutil.which("chromium"), shutil.which("chromium-browser"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(candidate)
    raise ValueError("Установленный Chrome не найден. Задайте --chrome или CHROME_PATH.")


class ApiFixtures:
    """All API traffic is synthetic; browser can't accidentally spend an API key."""

    def __init__(self, base_url):
        self.origin = urlsplit(base_url).netloc
        self.mode = "live"
        self.calls = []
        self.events = []
        self.hold_next = False
        self.pending = []
        self.fail_next = False
        self.question_data = None

    def question(self, answers):
        child = answers.get("patient_type") == "child"
        mode = self.mode if answers.get("ai_consent") else "rules"
        result = {
            "status": "question", "mode": mode, "id": "synthetic-ui-question", "token": "synthetic-ui-token-not-valid-on-server",
            "signals": [{"label": "Из анкеты", "value": "Зрение ребёнка" if child else "Усталость и ночные смены"}],
            "context": "Вы рассказали о чтении и усталости ребёнка." if child else "Вы отметили усталость и рассказали о работе по ночам.",
            "question": "Ребёнок видит хуже только во время чтения или также вдаль?" if child else "После отдыха между ночными сменами усталость становится меньше?",
            "why": "Ответ поможет врачу уточнить обстоятельства жалобы на первой консультации.",
            "placeholder": "Добавьте детали, которые важно обсудить с врачом",
            "options": [{"id": "after_rest", "label": "После отдыха становится легче", "detail": "Замечаю связь с режимом дня"}, {"id": "persists", "label": "Почти не меняется", "detail": "Усталость остаётся и после отдыха"}],
        }
        if child:
            result["options"] = [
                {"id": "near", "label": "Только при чтении", "detail": "Вблизи становится сложнее"},
                {"id": "distance", "label": "Также вдаль", "detail": "Например, при взгляде на доску"},
            ]
        if mode == "live":
            result["insight"] = {"title": "Важен контекст вашего ответа", "connection": "В анкете есть жалоба и обстоятельства, которые стоит обсудить вместе.", "missing_detail": "Когда ребёнку сложнее видеть" if child else "Как меняется самочувствие после отдыха"}
        self.question_data = result
        return result

    def plan(self, answers):
        base = deepcopy(answers)
        clarification = base.pop("clarification", {})
        result = recommend(base)
        if result["status"] != "recommended":
            return result
        mode = self.question_data["mode"]
        if clarification.get("skipped"):
            receipt = {"skipped": True, "mode": mode}
        else:
            detail = clarification.get("detail", "")
            child = answers.get("patient_type") == "child"
            before = "Обсудить жалобы на зрение ребёнка." if child else BEFORE
            after = "На приёме у педиатра обсудить, когда ребёнку сложнее видеть." if child else AFTER
            selected = next((item["label"] for item in self.question_data["options"] if item["id"] == clarification.get("option_id")), "Ответ своими словами")
            receipt = {
                "skipped": False, "mode": mode, "action": "continue",
                "question": self.question_data["question"],
                "answer_label": selected,
                "detail": detail, "impact_title": "Подготовили более точный разговор с врачом",
                "impact": after, "clinician_note": ("Со слов родителя: " if child else "Со слов пациента: ") + (detail or selected),
                "before": before, "after": after,
            }
            index = 1 if answers.get("patient_type") == "child" else 0
            result["route"][index]["detail"] += " " + after
        result["clarification"] = receipt
        result["report"]["clarification"] = receipt
        return result

    def handle(self, route):
        request = route.request
        url = urlsplit(request.url)
        if url.netloc != self.origin:
            route.abort()
            return
        if not url.path.startswith("/api/"):
            route.continue_()
            return
        data = request.post_data_json if request.method == "POST" else None
        self.calls.append((url.path, deepcopy(data)))
        if url.path == "/api/config":
            route.fulfill(json={"ai_available": True, "disclosure": "Синтетическая проверка интерфейса"})
        elif url.path == "/api/events":
            self.events.append(data)
            route.fulfill(status=202, json={"status": "ok"})
        elif url.path in ("/api/agent/clarify", "/api/agent/recommend"):
            if self.hold_next:
                self.hold_next = False
                self.pending.append(route)
                return
            if self.fail_next:
                self.fail_next = False
                events = [{"type": "error", "message": "Не удалось получить ответ ассистента. Попробуйте ещё раз."}]
            else:
                result = self.question(data) if url.path.endswith("clarify") else self.plan(data)
                events = [{"type": "stage", "id": "fixture", "title": "Проверяем ответы", "detail": "Синтетический сценарий интерфейса", "state": "complete"}, {"type": "result", "data": result}]
            route.fulfill(status=200, content_type="application/x-ndjson; charset=utf-8", body="".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events))
        else:
            route.fulfill(status=404, json={"error": "Для этого запроса нет тестового сценария."})


class BrowserSmoke(unittest.TestCase):
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
        self.context = self.browser.new_context(viewport={"width": 1440, "height": 1050}, locale="ru-RU", reduced_motion="reduce", accept_downloads=True)
        self.fixture = ApiFixtures(OPTIONS.base_url)
        self.context.route("**/*", self.fixture.handle)
        self.page = self.context.new_page()
        self.js_errors = []
        self.page.on("pageerror", lambda error: self.js_errors.append(str(error)))
        self.page.goto(OPTIONS.base_url, wait_until="networkidle")
        expect(self.page.locator("#submit-button")).to_be_enabled()
        expect(self.page.locator('[name="ai_consent"]')).not_to_be_checked()

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.js_errors, [], "Браузер сообщил об ошибке JavaScript")

    def adult(self, consent=False):
        self.page.locator("#age").fill("32")
        self.page.locator('label:has(input[name="sex"][value="male"])').click()
        self.page.locator('#concerns label:has(input[value="fatigue"])').click()
        self.page.locator("#notes").fill("Работаю ночными сменами, после смен устаю.")
        if consent:
            self.page.locator('[name="ai_consent"]').check()

    def open_question(self):
        self.page.locator("#submit-button").click()
        expect(self.page.locator("#assistant-question")).to_be_visible()
        return self.page.locator("dialog")

    def screenshot(self, name):
        if OPTIONS.screenshot_dir:
            directory = Path(OPTIONS.screenshot_dir)
            directory.mkdir(parents=True, exist_ok=True)
            if name.endswith("plan"):
                # Finish the application's smooth scroll before capturing the result.
                self.page.locator("#recommendation").evaluate("el => el.scrollIntoView({behavior: 'instant', block: 'start'})")
            self.page.screenshot(path=str(directory / ("fixture-" + name + ".png")), full_page=False)

    def assert_no_overflow(self):
        self.assertTrue(self.page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), "Страница выходит за ширину экрана")
        dialog = self.page.locator("dialog")
        if dialog.count():
            self.assertTrue(dialog.evaluate("el => el.scrollWidth <= el.clientWidth + 1"), "Диалог выходит за свою ширину")

    def test_live_fixture_custom_answer_receipt_route_metrics_and_deletion(self):
        self.adult(consent=True)
        dialog = self.open_question()
        expect(dialog.locator(".assistant-speaker small")).to_have_text("Живой ИИ-анализ")
        expect(dialog.locator(".connection-card")).to_be_visible()
        expect(dialog.locator(".assistant-evidence")).to_contain_text("Усталость и ночные смены")
        self.screenshot("desktop-question")
        dialog.locator('label:has(input[value="free_text"])').click()
        expect(dialog.locator(".assistant-confirm")).to_be_disabled()
        dialog.locator("#assistant-detail").fill(CUSTOM_REPLY)
        expect(dialog.locator(".assistant-confirm")).to_be_enabled()
        dialog.locator(".assistant-confirm").click()
        expect(self.page.locator("#recommendation .plan-delta")).to_contain_text(BEFORE)
        expect(self.page.locator("#recommendation .plan-delta")).to_contain_text(AFTER)
        expect(self.page.locator("#recommendation .route-card")).to_contain_text(AFTER)
        expect(self.page.locator("#health-card .receipt-compact")).to_contain_text(CUSTOM_REPLY)
        expect(self.page.locator("#recommendation .program-price")).to_contain_text(re.compile(r"59\s*900\s*₸"))
        submitted = [data for path, data in self.fixture.calls if path == "/api/agent/recommend"][-1]
        self.assertTrue(submitted["ai_consent"])
        self.assertEqual(submitted["clarification"]["option_id"], "free_text")
        self.assertEqual(submitted["clarification"]["detail"], CUSTOM_REPLY)
        self.screenshot("desktop-plan")
        with self.page.expect_response(lambda response: urlsplit(response.url).path == "/api/events" and response.request.post_data_json.get("event") == "satisfaction_submitted"):
            self.page.locator('[data-rating="5"]').click()
        expect(self.page.locator(".rating-controls [role=status]")).to_have_text("Спасибо за вашу оценку!")
        with self.page.expect_download() as saved:
            self.page.locator("#book-demo").click()
        self.assertTrue(saved.value.suggested_filename.endswith(".ics"))
        expect(self.page.locator("#booking-status")).to_contain_text("Демо запись сохранена")
        with self.page.expect_download() as saved:
            self.page.locator("#save-reminder").click()
        self.assertTrue(saved.value.suggested_filename.endswith(".ics"))
        self.page.wait_for_load_state("networkidle")
        event_names = [event["event"] for event in self.fixture.events]
        for name in ("questionnaire_started", "assistant_completed", "recommendation_ready", "satisfaction_submitted", "booking_intent", "reminder_intent"):
            self.assertIn(name, event_names)
        self.assertEqual(event_names.count("satisfaction_submitted"), 1)
        for event in self.fixture.events:
            self.assertLessEqual(set(event), {"event", "mode", "package_id", "duration_ms", "rating"})
        self.page.evaluate("localStorage.setItem('prime-checkup-legacy', 'synthetic fixture')")
        self.page.locator("#clear-health-data").click()
        for section in ("#recommendation", "#booking", "#health-card", "#reminder"):
            expect(self.page.locator(section)).to_be_hidden()
        expect(self.page.locator("#age")).to_have_value("")
        expect(self.page.locator('[name="ai_consent"]')).not_to_be_checked()
        self.assertTrue(self.page.evaluate("Object.keys(sessionStorage).every(key => !key.startsWith('prime-checkup-'))"))
        self.assertTrue(self.page.evaluate("Object.keys(localStorage).every(key => !key.startsWith('prime-checkup-'))"))

    def test_without_consent_rules_mode_and_skipping(self):
        self.adult()
        dialog = self.open_question()
        expect(dialog.locator(".assistant-speaker small")).to_have_text("Подбор по правилам")
        expect(dialog.locator('input[value="free_text"]')).to_have_count(0)
        dialog.locator(".assistant-skip").click()
        expect(self.page.locator("#recommendation .assistant-skipped")).to_contain_text("Уточнение пропущено")
        for path, data in self.fixture.calls:
            if path.startswith("/api/agent/"):
                self.assertFalse(data["ai_consent"])

    def test_fallback_is_explicit_and_never_labeled_live(self):
        self.fixture.mode = "fallback"
        self.adult(consent=True)
        dialog = self.open_question()
        expect(dialog.locator(".agent-fallback")).to_contain_text("Не удалось получить проверенное ИИ-уточнение")
        expect(dialog.locator(".assistant-speaker small")).to_have_text("Резервный подбор")
        expect(dialog.locator('input[value="free_text"]')).to_have_count(0)
        dialog.locator('label:has(input[value="after_rest"])').click()
        dialog.locator(".assistant-confirm").click()
        expect(self.page.locator("#recommendation .receipt-tag")).to_have_text("Уточнение учтено ✓")

    def test_question_escape_and_close_return_to_same_answers(self):
        self.adult(consent=True)
        self.open_question()
        self.page.keyboard.press("Escape")
        expect(self.page.locator("dialog")).to_have_count(0)
        expect(self.page.locator("#submit-button")).to_be_focused()
        expect(self.page.locator("#age")).to_have_value("32")
        self.open_question().get_by_role("button", name="Вернуться к анкете", exact=True).click()
        expect(self.page.locator("dialog")).to_have_count(0)
        self.assertFalse(any(path.endswith("/recommend") for path, _ in self.fixture.calls))

    def test_processing_can_be_cancelled_and_error_is_recoverable(self):
        self.adult(consent=True)
        self.fixture.hold_next = True
        self.page.locator("#submit-button").click()
        expect(self.page.locator("#processing-title")).to_be_visible()
        self.page.locator(".processing-cancel").click()
        expect(self.page.locator("dialog")).to_have_count(0)
        expect(self.page.locator("#submit-button")).to_be_enabled()
        for pending in self.fixture.pending:
            try:
                pending.abort()
            except PlaywrightError:
                pass  # The AbortController may have already closed the intercepted request.
        self.fixture.fail_next = True
        self.page.locator("#submit-button").click()
        expect(self.page.locator("#form-error")).to_contain_text("Не удалось получить ответ ассистента")
        expect(self.page.locator("#submit-button")).to_be_enabled()
        self.open_question()

    def test_mobile_parent_flow_and_no_horizontal_overflow(self):
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.page.locator('label:has(input[name="patient_type"][value="child"])').click()
        self.page.locator("#child-age").fill("8")
        self.page.locator('label:has(input[name="child_sex"][value="female"])').click()
        self.page.locator('#child-concerns label:has(input[value="vision"])').click()
        self.page.locator("#submit-button").click()
        expect(self.page.locator("#form-error")).to_contain_text("родитель")
        self.assertFalse(any(path.startswith("/api/agent/") for path, _ in self.fixture.calls))
        self.page.locator('[name="guardian_confirmed"]').check()
        self.page.locator('[name="ai_consent"]').check()
        dialog = self.open_question()
        expect(dialog.locator("#assistant-question")).to_contain_text("Ребёнок")
        self.assert_no_overflow()
        self.screenshot("mobile-question")
        dialog.locator('label:has(input[value="near"])').click()
        dialog.locator(".assistant-confirm").click()
        expect(self.page.locator("#health-card h2")).to_have_text("Демо-отчёт ребёнка")
        expect(self.page.locator("#recommendation .program-card h3")).to_have_text("Детский check-up PRIME")
        self.assert_no_overflow()
        self.screenshot("mobile-plan")
        sent = [data for path, data in self.fixture.calls if path == "/api/agent/clarify"][-1]
        self.assertEqual(sent["patient_type"], "child")
        self.assertTrue(sent["guardian_confirmed"])
        self.assertNotIn("concerns", sent)


def main():
    global OPTIONS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--chrome", help="Путь к установленному Chrome/Chromium")
    parser.add_argument("--screenshot-dir", help="Каталог необязательных скриншотов синтетических сценариев")
    OPTIONS = parser.parse_args()
    parsed = urlsplit(OPTIONS.base_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        parser.error("Укажите полный адрес запущенного приложения.")
    print("UI smoke: synthetic API fixtures only; external provider calls are blocked.", flush=True)
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(BrowserSmoke))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
