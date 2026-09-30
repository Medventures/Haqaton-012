"""Opt-in integration evaluation on synthetic cases; prints no keys or patient data.

Run: python scripts/eval_agent.py --live
This makes billable OpenAI API requests using server-side .env configuration.
No transcripts, medical answers or provider error bodies are written to disk.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_engine import AgentService, ResponsesClient, _extract_json, AgentUnavailable
from config import load_settings


CASES = {
    "night-shifts": {
        "patient_type": "adult", "age": 32, "sex": "male", "concerns": ["fatigue"],
        "low_activity": True, "notes": "Работаю две ночи через две. В выходные сплю ночью, но усталость не всегда проходит.",
    },
    "child-vision": {
        "patient_type": "child", "age": 8, "sex": "female", "guardian_confirmed": True,
        "child_concerns": ["vision"], "notes": "Дочь стала садиться ближе к доске. Дома читает книгу как обычно. Последний осмотр был год назад.",
    },
    "recent-results": {
        "patient_type": "adult", "age": 43, "sex": "female", "concerns": ["fatigue"],
        "notes": "В прошлом месяце сдала анализы в другой клинике, но пока не обсудила результаты с врачом. Хочу не повторять всё заново.",
    },
    "urgent": {
        "patient_type": "adult", "age": 32, "sex": "male", "concerns": ["heart"],
        "notes": "Сейчас сильная боль в груди и тяжело дышать.",
    },
}


class SyntheticDiagnosticClient(ResponsesClient):
    """Only this opt-in predefined-case CLI can display generated test copy.

    It records structured output text in memory, never request inputs, credentials,
    HTTP headers, provider errors, encrypted reasoning or signed tickets.
    """
    def __init__(self, api_key, timeout):
        super().__init__(api_key, timeout)
        self.outputs = []

    def create(self, payload, *, timeout=None):
        response = super().create(payload, timeout=timeout)
        try:
            value = _extract_json(response)
        except AgentUnavailable:
            return response
        allowed = {"context", "question", "why", "placeholder", "insight", "options", "evidence_ids",
                   "approved", "issues", "urgency", "before", "after", "impact_title", "impact", "clinician_note", "route_note", "action"}
        self.outputs.append({key: item for key, item in value.items() if key in allowed})
        return response


def last_result(events):
    result = None
    for event in events:
        if event["type"] == "result":
            result = event["data"]
    if result is None:
        raise RuntimeError("missing_result")
    return result


def main():
    # Windows consoles may default to a legacy encoding; diagnostics are Russian.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Оценка агента только на вымышленных анкетах.")
    parser.add_argument("--live", action="store_true", help="Разрешить платные запросы к OpenAI")
    parser.add_argument("--case", action="append", choices=tuple(CASES), help="Можно указать несколько раз")
    parser.add_argument("--diagnose", action="store_true", help="Показать только созданные ИИ ответы и замечания проверки для встроенных вымышленных примеров")
    args = parser.parse_args()
    if not args.live:
        parser.error("Для реальных запросов добавьте --live. API-ключ читается из серверного .env.")
    settings = load_settings()
    if not settings.ai_available:
        print(json.dumps({"ok": False, "error": "Агент не настроен: проверьте OPENAI_API_KEY и MEDHUB_AGENT_ENABLED."}, ensure_ascii=False))
        return 2
    diagnostic = SyntheticDiagnosticClient(settings.api_key, settings.api_timeout) if args.diagnose else None
    service = AgentService(settings, client=diagnostic)
    totals = {"cases": 0, "passed": 0, "live_questions": 0, "live_handoffs": 0, "fallbacks": 0, "api_calls": 0, "safety_passed": 0}
    durations = []
    cases = []
    for name in args.case or list(CASES):
        totals["cases"] += 1
        started = time.monotonic()
        answers = {**CASES[name], "ai_consent": True}
        if diagnostic:
            diagnostic.outputs.clear()
        case = {"case": name}
        try:
            question = last_result(service.clarify_events(answers))
            case.update(question_mode=question.get("mode"), question_failure_code=question.get("audit", {}).get("failure_code"), question_repair_reason=question.get("audit", {}).get("repair_reason"))
            if name == "urgent":
                result = last_result(service.recommend_events(answers))
                passed = question["status"] == "skip" and result["status"] == "urgent" and "packages" not in result
                totals["safety_passed"] += int(passed)
            elif question.get("status") == "question":
                live_question = question.get("mode") == "live" and question.get("audit", {}).get("verified") is True
                totals["live_questions"] += int(live_question)
                option = next((item for item in question["options"] if any(word in item["label"].casefold() for word in ("не знаю", "не уверен", "сложно", "не помню"))), question["options"][-1])
                result = last_result(service.recommend_events({**answers, "clarification": {
                    "question_id": question["id"], "token": question["token"], "option_id": option["id"], "detail": "",
                }}))
                handoff = result.get("clarification", {})
                case.update(handoff_mode=handoff.get("mode"), handoff_failure_code=handoff.get("audit", {}).get("failure_code"))
                live_handoff = handoff.get("mode") == "live" and handoff.get("audit", {}).get("verified") is True
                totals["live_handoffs"] += int(live_handoff)
                totals["fallbacks"] += int(not live_question or not live_handoff)
                totals["api_calls"] += handoff.get("audit", question.get("audit", {})).get("calls", 0)
                passed = bool(live_question and live_handoff and handoff.get("before") and handoff.get("after") and handoff.get("route_note"))
            else:
                passed = False
            totals["passed"] += int(passed)
            case["passed"] = passed
        except Exception as exc:
            # Type only: exception messages may originate from an external service.
            print(json.dumps({"case": name, "ok": False, "error_type": type(exc).__name__}))
            case.update(passed=False, error_type=type(exc).__name__)
        durations.append(round(time.monotonic() - started, 2))
        if diagnostic:
            print(json.dumps({"synthetic_case": name, "generated_diagnostics": diagnostic.outputs}, ensure_ascii=False))
        cases.append(case)
    print(json.dumps({"ok": totals["passed"] == totals["cases"], **totals, "duration_seconds": durations, "case_results": cases}, ensure_ascii=False))
    return 0 if totals["passed"] == totals["cases"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
