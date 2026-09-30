import base64
import json
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError

from agent_engine import AgentService, AgentUnavailable, ResponsesClient, _RunAudit, _text_safety, canonical_answers, evidence_ledger


def settings(**overrides):
    return SimpleNamespace(**({"api_key": "test-only-not-a-key", "model": "gpt-5-mini", "api_timeout": 1, "signing_secret": "s" * 64, "agent_enabled": True} | overrides))


def adult(**overrides):
    return {"patient_type": "adult", "age": 32, "sex": "male", "concerns": ["fatigue", "pressure"], "notes": "Работаю по ночам, утром устаю.", "ai_consent": True, **overrides}


def output(data):
    return {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(data, ensure_ascii=False)}]}]}


def tools_response():
    return {"status": "completed", "output": [
        {"type": "reasoning", "id": "rs_example", "summary": []},
        *[{"type": "function_call", "name": name, "arguments": "{}", "call_id": "call_" + str(index)}
          for index, name in enumerate(("inspect_evidence", "inspect_catalog", "get_baseline_plan"))],
    ]}


def question():
    return {
        "context": "Вы отметили усталость и написали, что работаете по ночам.",
        "question": "Усталость остаётся и после нескольких дней с обычным ночным сном?",
        "why": "Это поможет врачу уточнить связь ваших ощущений с режимом работы.",
        "placeholder": "Например, как чувствуете себя в выходные…",
        "evidence_ids": ["concern.fatigue", "answer.notes"],
        "insight": {"title": "Важен отдых между сменами", "connection": "Усталость отмечена вместе с ночным графиком.", "missing_detail": "Пока неизвестно, как вы чувствуете себя после отдыха."},
        "options": [
            {"id": "o1", "label": "После отдыха становится легче", "detail": "Замечаю разницу в выходные", "action": "continue"},
            {"id": "o2", "label": "Усталость остаётся", "detail": "Даже после привычного сна", "action": "continue"},
            {"id": "o3", "label": "Пока не знаю", "detail": "Не было возможности сравнить", "action": "continue"},
        ],
    }


def synthesis():
    return {"impact_title": "Отдых помогает — врач увидит эту деталь", "impact": "На первой встрече врач сможет уточнить режим сна и изменения самочувствия между сменами.", "clinician_note": "Пациент отмечает усталость и ночную работу. После отдыха становится легче. Уточнить режим сна и длительность жалоб.", "route_note": "Обсудить ночной график, восстановление после отдыха и длительность усталости.", "before": "Не было известно, как меняется усталость после отдыха.", "after": "Вы отметили, что после отдыха становится легче.", "action": "continue", "evidence_ids": ["answer.notes", "answer.selected"]}


REVIEW = {"approved": True, "issues": [], "urgency": "continue"}


def review_issue(reason, field="context", quote=None):
    return {"field": field, "quote": quote or question()["context"], "reason": reason}


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def create(self, payload):
        self.requests.append(deepcopy(payload))
        if not self.responses:
            raise AssertionError("Unexpected external API call")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return deepcopy(response)


def final(events):
    values = list(events)
    assert values[-1]["type"] == "result"
    return values[-1]["data"]


def answer_to(q, **overrides):
    return {"question_id": q["id"], "option_id": q["options"][0]["id"], "token": q["token"], **overrides}


class AgentEngineTests(unittest.TestCase):
    def test_real_tool_loop_and_independent_review_have_provenance(self):
        client = FakeClient([tools_response(), output(question()), output(REVIEW)])
        service = AgentService(settings(), client=client)
        result = final(service.clarify_events(adult()))
        self.assertEqual(result["mode"], "live")
        self.assertEqual(result["audit"]["calls"], 3)
        self.assertTrue(result["audit"]["verified"])
        self.assertEqual(len(result["audit"]["tool_names"]), 3)
        self.assertNotIn("action", result["options"][0])
        self.assertIn("token", result)
        self.assertEqual(client.requests[0]["tool_choice"], "required")
        self.assertTrue(any(x.get("type") == "reasoning" for x in client.requests[1]["input"]))
        self.assertEqual(sum(x.get("type") == "function_call_output" for x in client.requests[1]["input"]), 3)
        self.assertTrue(all(p["store"] is False for p in client.requests))
        self.assertTrue(all(p["text"]["format"]["strict"] for p in client.requests))
        self.assertNotEqual(client.requests[1]["instructions"], client.requests[2]["instructions"])

    def test_live_answer_changes_route_and_report_not_package_price(self):
        client = FakeClient([tools_response(), output(question()), output(REVIEW), output(synthesis()), output(REVIEW)])
        service = AgentService(settings(), client=client)
        values = adult()
        q = final(service.clarify_events(values))
        result = final(service.recommend_events({**values, "clarification": answer_to(q)}))
        self.assertEqual(result["checkup_id"], "heart")
        self.assertEqual(result["price_tenge"], 69900)
        self.assertEqual(result["clarification"]["mode"], "live")
        self.assertEqual(result["clarification"]["audit"]["calls"], 5)
        for route in [result["route"], *(x["route"] for x in result["packages"])]:
            self.assertIn("ночной график", route[0]["detail"])
        self.assertEqual(result["report"]["clarification"]["after"], synthesis()["after"])
        permitted_ids = client.requests[3]["text"]["format"]["schema"]["properties"]["evidence_ids"]["items"]["enum"]
        self.assertIn("answer.selected", permitted_ids)
        self.assertIn("answer.notes", permitted_ids)
        self.assertNotIn("answer.detail", permitted_ids)

    def test_no_consent_never_calls_provider_even_for_answer(self):
        client = FakeClient([])
        service = AgentService(settings(), client=client)
        values = adult(ai_consent=False)
        q = final(service.clarify_events(values))
        result = final(service.recommend_events({**values, "clarification": answer_to(q)}))
        self.assertEqual(q["mode"], "rules")
        self.assertEqual(result["clarification"]["mode"], "rules")
        self.assertEqual(client.requests, [])

    def test_provider_failure_is_honest_fallback_and_signed(self):
        client = FakeClient([AgentUnavailable("timeout")])
        service = AgentService(settings(), client=client)
        values = adult()
        q = final(service.clarify_events(values))
        self.assertEqual(q["mode"], "fallback")
        result = final(service.recommend_events({**values, "clarification": answer_to(q)}))
        self.assertEqual(result["status"], "recommended")
        self.assertEqual(result["clarification"]["mode"], "fallback")

    def test_total_operation_deadline_stops_chain_and_never_enters_ticket(self):
        elapsed = [0]
        client = FakeClient([tools_response(), output(question())])
        original_create = client.create

        def slow_create(payload):
            response = original_create(payload)
            elapsed[0] += 46
            return response

        client.create = slow_create
        service = AgentService(settings(), client=client, monotonic=lambda: elapsed[0])
        result = final(service.clarify_events(adult()))
        self.assertEqual(result["mode"], "fallback")
        self.assertEqual(result["audit"]["failure_code"], "operation_timeout")
        self.assertEqual(len(client.requests), 2)
        raw = result["token"].split(".")[0]
        payload = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode()
        self.assertNotIn("deadline", payload)
        self.assertNotIn("operation_calls", payload)

    def test_transport_timeout_is_capped_to_remaining_operation_budget(self):
        elapsed = [0]
        client = ResponsesClient("test-key", timeout=35)
        responses = [tools_response(), output(question()), output(REVIEW)]
        timeouts = []

        def create(payload, *, timeout):
            timeouts.append(timeout)
            if len(timeouts) == 1:
                elapsed[0] = 70
            return responses.pop(0)

        with patch.object(client, "create", side_effect=create):
            result = final(AgentService(settings(api_timeout=35), client=client, monotonic=lambda: elapsed[0]).clarify_events(adult()))
        self.assertEqual(result["mode"], "live")
        self.assertEqual(timeouts, [35, 20, 20])

    def test_operation_call_budget_is_independent_of_cumulative_audit(self):
        client = FakeClient([output(REVIEW)] * 8)
        service = AgentService(settings(), client=client)
        audit = _RunAudit({"calls": 10}, service.monotonic)
        for _ in range(8):
            service._request("Проверка", [], {}, audit)
        with self.assertRaisesRegex(AgentUnavailable, "operation_call_budget"):
            service._request("Проверка", [], {}, audit)
        self.assertEqual(len(client.requests), 8)
        self.assertEqual(audit["calls"], 18)

    def test_tampering_expiry_and_binding_fail_before_provider(self):
        now = [1000]
        client = FakeClient([])
        service = AgentService(settings(), client=client, clock=lambda: now[0])
        values = adult(ai_consent=False)
        q = final(service.clarify_events(values))
        bad = answer_to(q)
        bad["token"] = "x" + bad["token"][1:]
        with self.assertRaises(ValueError):
            final(service.recommend_events({**values, "clarification": bad}))
        with self.assertRaises(ValueError):
            final(service.recommend_events({**values, "age": 33, "clarification": answer_to(q)}))
        now[0] += 1201
        with self.assertRaises(ValueError):
            final(service.recommend_events({**values, "clarification": answer_to(q)}))
        self.assertEqual(client.requests, [])

    def test_forged_option_and_missing_token_rejected(self):
        service = AgentService(settings(), client=FakeClient([]))
        values = adult(ai_consent=False)
        q = final(service.clarify_events(values))
        for clarification in (answer_to(q, option_id="invented"), answer_to(q, token=""), answer_to(q, question_id="forged")):
            with self.assertRaises(ValueError):
                final(service.recommend_events({**values, "clarification": clarification}))

    def test_child_evidence_excludes_hidden_adult_fields(self):
        values = adult(patient_type="child", age=8, guardian_confirmed=True, child_concerns=["vision"], smoking=True, chronic=True, family=["heart"])
        ledger = evidence_ledger(values)
        ids = {item["id"] for item in ledger}
        self.assertNotIn("concern.pressure", ids)
        self.assertNotIn("answer.smoking", ids)
        self.assertNotIn("family.heart", ids)
        self.assertIn("concern.vision", ids)
        self.assertNotIn("smoking", canonical_answers(values))

    def test_ungrounded_question_never_shown(self):
        forged = question()
        forged["evidence_ids"] = ["invented.diagnosis"]
        client = FakeClient([tools_response(), output(forged), output(forged)])
        q = final(AgentService(settings(), client=client).clarify_events(adult()))
        self.assertEqual(q["mode"], "fallback")

    def test_invalid_draft_gets_one_repair_then_independent_review(self):
        invalid = question()
        invalid["why"] = ""
        client = FakeClient([tools_response(), output(invalid), output(question()), output(REVIEW)])
        q = final(AgentService(settings(), client=client).clarify_events(adult()))
        self.assertEqual(q["mode"], "live")
        self.assertEqual(q["audit"]["repair_reason"], "invalid_text_question_why")
        self.assertEqual(len(client.requests), 4)

    def test_structural_and_semantic_rejection_share_one_repair_budget(self):
        invalid = question()
        invalid["why"] = ""
        rejected = {"approved": False, "issues": [review_issue("Не удалось подтвердить вывод")], "urgency": "continue"}
        client = FakeClient([tools_response(), output(invalid), output(question()), output(rejected)])
        q = final(AgentService(settings(), client=client).clarify_events(adult()))
        self.assertEqual(q["mode"], "fallback")
        self.assertEqual(len(client.requests), 4)

    def test_nested_future_question_is_repaired_before_patient_sees_it(self):
        invalid = question()
        invalid["question"] = "Вы будете сейчас спать нормально — да или нет? Если нет, как изменяется сон?"
        client = FakeClient([tools_response(), output(invalid), output(question()), output(REVIEW)])
        result = final(AgentService(settings(), client=client).clarify_events(adult()))
        self.assertEqual(result["mode"], "live")
        self.assertEqual(result["question"], question()["question"])
        self.assertEqual(result["audit"]["repair_reason"], "question_not_single_observation")

    def test_impersonal_context_and_diagnostic_options_are_not_published(self):
        for field in ("context", "option", "mixed_unknown"):
            with self.subTest(field=field):
                invalid = question()
                if field == "context":
                    invalid["context"] = "Пациент — мужчина, работает ночью, жалуется на усталость."
                elif field == "option":
                    invalid["options"][0]["detail"] = "Указывает на возможную хроническую усталость"
                else:
                    invalid["options"][2]["label"] = "Пока не знаю / зависит от дня"
                client = FakeClient([tools_response(), output(invalid), output(question()), output(REVIEW)])
                result = final(AgentService(settings(), client=client).clarify_events(adult()))
                self.assertEqual(result["mode"], "live")
                self.assertEqual(result["context"], question()["context"])
                self.assertEqual(result["options"][0]["detail"], question()["options"][0]["detail"])
                self.assertEqual(result["options"][2]["label"], "Пока не знаю")

    def test_unknown_answer_cannot_become_a_confirmed_pattern(self):
        wrong = synthesis()
        wrong["after"] = "Вы сообщили, что сон непостоянный и отдых не помогает."
        client = FakeClient([tools_response(), output(question()), output(REVIEW), output(wrong), output(wrong)])
        service = AgentService(settings(), client=client)
        values = adult()
        q = final(service.clarify_events(values))
        result = final(service.recommend_events({**values, "clarification": answer_to(q, option_id="o3")}))
        handoff = result["clarification"]
        self.assertEqual(handoff["mode"], "fallback")
        self.assertEqual(handoff["after"], "Пока не знаю")
        self.assertNotIn("непостоянный", handoff["clinician_note"])
        self.assertNotIn("отдых не помогает", result["route"][0]["detail"])

    def test_unknown_answer_can_keep_uncertainty_in_live_handoff(self):
        unknown = synthesis()
        unknown.update(after="Вы пока не сравнивали самочувствие после отдыха. Это ещё нужно уточнить.",
                       impact_title="Осталась тема для первой встречи",
                       impact="Врач поможет описать, как вы чувствуете себя после смен и выходных.",
                       clinician_note="Пациент пока не сравнивал самочувствие после отдыха; закономерность неизвестна.",
                       route_note="Обсудить, замечали ли вы разницу в самочувствии после смен и выходных.")
        client = FakeClient([tools_response(), output(question()), output(REVIEW), output(unknown), output(REVIEW)])
        service = AgentService(settings(), client=client)
        values = adult()
        q = final(service.clarify_events(values))
        result = final(service.recommend_events({**values, "clarification": answer_to(q, option_id="o3")}))
        self.assertEqual(result["clarification"]["mode"], "live")
        self.assertIn("пока не сравнивали", result["clarification"]["after"])
        synthesis_input = json.loads(client.requests[3]["input"][0]["content"])
        self.assertTrue(synthesis_input["answer"]["answer_uncertain"])

    def test_real_uncertain_wording_is_not_treated_as_a_definite_answer(self):
        for label in ("Пока не могу сказать / не отслеживал", "Не обращал внимания", "Затрудняюсь ответить"):
            with self.subTest(label=label):
                draft = question()
                draft["options"][2]["label"] = label
                client = FakeClient([tools_response(), output(draft), output(REVIEW), output(synthesis()), output(synthesis())])
                service = AgentService(settings(), client=client)
                values = adult()
                q = final(service.clarify_events(values))
                result = final(service.recommend_events({**values, "clarification": answer_to(q, option_id="o3")}))
                self.assertEqual(result["clarification"]["mode"], "fallback")
                self.assertEqual(result["clarification"]["after"], label)

    def test_review_rejection_repairs_once_then_falls_back(self):
        rejected = {"approved": False, "issues": [review_issue("Указан неподтверждённый факт")], "urgency": "continue"}
        client = FakeClient([tools_response(), output(question()), output(rejected), output(question()), output(rejected)])
        q = final(AgentService(settings(), client=client).clarify_events(adult()))
        self.assertEqual(q["mode"], "fallback")
        self.assertEqual(len(client.requests), 5)

    def test_free_text_answer_supported_without_forcing_option(self):
        service = AgentService(settings(), client=FakeClient([]))
        values = adult(ai_consent=False)
        q = final(service.clarify_events(values))
        result = final(service.recommend_events({**values, "clarification": answer_to(q, option_id="free_text", detail="Хочу обсудить сон после ночной работы.")}))
        self.assertEqual(result["clarification"]["answer_label"], "Ответ своими словами")
        self.assertIn("ночной работы", result["report"]["clarification"]["detail"])
        with self.assertRaises(ValueError):
            final(service.recommend_events({**values, "clarification": answer_to(q, option_id="free_text", detail="")}))

    def test_synthesis_failure_preserves_real_words_and_labels_fallback(self):
        client = FakeClient([tools_response(), output(question()), output(REVIEW), AgentUnavailable("timeout")])
        service = AgentService(settings(), client=client)
        values = adult()
        q = final(service.clarify_events(values))
        result = final(service.recommend_events({**values, "clarification": answer_to(q, detail="Два дня отдыха помогают")}))
        note = result["clarification"]
        self.assertEqual(note["mode"], "fallback")
        self.assertFalse(note["audit"]["verified"])
        self.assertIn("Два дня отдыха помогают", note["clinician_note"])

    def test_synthesis_language_failure_gets_one_repair_and_review(self):
        invalid = synthesis()
        invalid["clinician_note"] = "Пациент принёс PDF с результатами."
        client = FakeClient([tools_response(), output(question()), output(REVIEW), output(invalid), output(synthesis()), output(REVIEW)])
        service = AgentService(settings(), client=client)
        values = adult()
        q = final(service.clarify_events(values))
        result = final(service.recommend_events({**values, "clarification": answer_to(q)}))
        self.assertEqual(result["clarification"]["mode"], "live")
        self.assertEqual(result["clarification"]["audit"]["synthesis_repair_reason"], "invalid_language_synthesis_clinician_note")
        self.assertEqual(len(client.requests), 6)
        repair = json.loads(client.requests[4]["input"][0]["content"])
        self.assertEqual(repair["answer"]["selected"], question()["options"][0]["label"])
        self.assertIn("answer.selected", [item["id"] for item in repair["evidence"]])

    def test_synthesis_review_rejection_can_be_repaired_once(self):
        rejected = {"approved": False, "issues": [{"field": "impact", "reason": "Уточните влияние на первую беседу"}], "urgency": "continue"}
        client = FakeClient([tools_response(), output(question()), output(REVIEW), output(synthesis()), output(rejected), output(synthesis()), output(REVIEW)])
        service = AgentService(settings(), client=client)
        values = adult()
        q = final(service.clarify_events(values))
        result = final(service.recommend_events({**values, "clarification": answer_to(q)}))
        self.assertEqual(result["clarification"]["mode"], "live")
        self.assertEqual(result["clarification"]["audit"]["synthesis_repair_reason"], "review_rejected")
        self.assertEqual(len(client.requests), 7)

    def test_second_invalid_synthesis_falls_back_with_original_answer(self):
        invalid = synthesis()
        invalid["clinician_note"] = "Some English text"
        client = FakeClient([tools_response(), output(question()), output(REVIEW), output(invalid), output(invalid)])
        service = AgentService(settings(), client=client)
        values = adult()
        q = final(service.clarify_events(values))
        result = final(service.recommend_events({**values, "clarification": answer_to(q)}))
        self.assertEqual(result["clarification"]["mode"], "fallback")
        self.assertEqual(result["clarification"]["answer_label"], question()["options"][0]["label"])
        self.assertEqual(len(client.requests), 5)

    def test_synthesis_local_repair_and_review_share_one_budget(self):
        invalid = synthesis()
        invalid["clinician_note"] = "English"
        rejected = {"approved": False, "issues": [{"field": "impact", "reason": "Вывод не подтверждён"}], "urgency": "continue"}
        client = FakeClient([tools_response(), output(question()), output(REVIEW), output(invalid), output(synthesis()), output(rejected)])
        service = AgentService(settings(), client=client)
        values = adult()
        q = final(service.clarify_events(values))
        result = final(service.recommend_events({**values, "clarification": answer_to(q)}))
        self.assertEqual(result["clarification"]["mode"], "fallback")
        self.assertEqual(len(client.requests), 6)

    def test_synthesis_safety_escalation_survives_invalid_prose_without_retry(self):
        invalid = synthesis()
        invalid.update(action="urgent", clinician_note="English")
        client = FakeClient([tools_response(), output(question()), output(REVIEW), output(invalid)])
        service = AgentService(settings(), client=client)
        values = adult()
        q = final(service.clarify_events(values))
        result = final(service.recommend_events({**values, "clarification": answer_to(q)}))
        self.assertEqual(result["status"], "urgent")
        self.assertEqual(result["clarification"]["action"], "urgent")
        self.assertNotIn("packages", result)
        self.assertEqual(len(client.requests), 4)

    def test_skip_does_not_call_synthesis_or_change_route(self):
        client = FakeClient([tools_response(), output(question()), output(REVIEW)])
        service = AgentService(settings(), client=client)
        values = adult()
        q = final(service.clarify_events(values))
        result = final(service.recommend_events({**values, "clarification": answer_to(q, option_id=None, skipped=True)}))
        self.assertTrue(result["clarification"]["skipped"])
        self.assertEqual(len(client.requests), 3)
        self.assertNotIn("уточняющий", result["route"][0]["detail"])

    def test_acute_original_and_answer_bypass_network_and_packages(self):
        service = AgentService(settings(), client=FakeClient([]))
        values = adult(notes="Сейчас сильная боль в груди", ai_consent=False)
        self.assertEqual(final(service.clarify_events(values))["status"], "skip")
        result = final(service.recommend_events(values))
        self.assertEqual(result["status"], "urgent")
        self.assertNotIn("packages", result)
        values = adult(ai_consent=False)
        q = final(service.clarify_events(values))
        result = final(service.recommend_events({**values, "clarification": answer_to(q, option_id="free_text", detail="Сейчас сильно болит грудь")}))
        self.assertEqual(result["status"], "urgent")
        self.assertNotIn("report", result)

    def test_initial_urgent_and_pregnancy_never_call_provider(self):
        client = FakeClient([])
        service = AgentService(settings(), client=client)
        for values in (adult(urgent=True), adult(sex="female", pregnancy=True)):
            self.assertEqual(final(service.clarify_events(values))["status"], "skip")
            self.assertNotEqual(final(service.recommend_events(values))["status"], "recommended")
        self.assertEqual(client.requests, [])

    def test_safety_gate_does_not_block_negated_or_ordinary_notes(self):
        self.assertEqual(_text_safety("Боли в груди нет. Устаю после ночной смены."), "continue")
        self.assertEqual(_text_safety("Принимаю препарат по назначению врача"), "continue")
        self.assertEqual(_text_safety("Ребёнок перестал говорить, хотя раньше умел"), "consultation")
        self.assertEqual(_text_safety("Сейчас боли в груди нет, но тяжело дышать"), "urgent")
        self.assertEqual(_text_safety("Не могу дышать"), "urgent")

    def test_unknown_tool_never_executes(self):
        response = {"output": [{"type": "function_call", "name": "run_shell", "arguments": "{}", "call_id": "bad"}]}
        client = FakeClient([response])
        self.assertEqual(final(AgentService(settings(), client=client).clarify_events(adult()))["mode"], "fallback")

    def test_independent_review_can_stop_original_flow(self):
        client = FakeClient([tools_response(), output(question()), output({"approved": True, "issues": [], "urgency": "consultation"})])
        result = final(AgentService(settings(), client=client).clarify_events(adult()))
        self.assertEqual(result["status"], "consultation")
        self.assertNotIn("packages", result)

    def test_rejected_question_preserves_urgent_review_without_attempting_repair(self):
        rejected = {"approved": False, "issues": ["Нельзя продолжать подбор при текущих опасных жалобах"], "urgency": "urgent"}
        client = FakeClient([tools_response(), output(question()), output(rejected), AgentUnavailable("repair_unavailable")])
        result = final(AgentService(settings(), client=client).clarify_events(adult()))
        self.assertEqual(result["status"], "urgent")
        self.assertEqual(len(client.requests), 3)
        self.assertNotIn("packages", result)
        self.assertNotIn("question", result)

    def test_rejected_repair_preserves_consultation_review(self):
        first_review = {"approved": False, "issues": [review_issue("Уточнить формулировку")], "urgency": "continue"}
        second_review = {"approved": False, "issues": ["Требуется разговор с врачом"], "urgency": "consultation"}
        client = FakeClient([tools_response(), output(question()), output(first_review), output(question()), output(second_review)])
        result = final(AgentService(settings(), client=client).clarify_events(adult()))
        self.assertEqual(result["status"], "consultation")
        self.assertEqual(len(client.requests), 5)
        self.assertNotIn("options", result)

    def test_rejected_synthesis_preserves_review_urgency_and_discards_prose(self):
        for action in ("urgent", "consultation"):
            with self.subTest(action=action):
                rejected = {"approved": False, "issues": ["Сначала требуется медицинская помощь"], "urgency": action}
                client = FakeClient([tools_response(), output(question()), output(REVIEW), output(synthesis()), output(rejected)])
                service = AgentService(settings(), client=client)
                values = adult()
                q = final(service.clarify_events(values))
                result = final(service.recommend_events({**values, "clarification": answer_to(q)}))
                self.assertEqual(result["status"], action)
                self.assertEqual(result["clarification"]["action"], action)
                self.assertEqual(result["clarification"]["mode"], "fallback")
                self.assertEqual(result["clarification"]["audit"]["failure_code"], "review_rejected")
                self.assertNotEqual(result["clarification"]["clinician_note"], synthesis()["clinician_note"])
                self.assertNotIn("packages", result)
                self.assertNotIn("report", result)

    def test_identifiers_redacted_before_provider_tools(self):
        ledger = evidence_ledger(adult(notes="Телефон +7 777 123 45 67, ИИН 123456789012, email test@example.com"))
        text = json.dumps(ledger, ensure_ascii=False)
        self.assertNotIn("123456789012", text)
        self.assertNotIn("test@example.com", text)
        self.assertIn("скрыт", text)

    def test_reviewer_cannot_cite_a_field_from_the_other_stage(self):
        rejected = {"approved": False, "issues": [review_issue("Необоснованный итог", field="after")], "urgency": "continue"}
        client = FakeClient([tools_response(), output(question()), output(rejected)])
        result = final(AgentService(settings(), client=client).clarify_events(adult()))
        self.assertEqual(result["mode"], "fallback")
        self.assertEqual(result["audit"]["failure_code"], "invalid_review_field")
        allowed = client.requests[2]["text"]["format"]["schema"]["properties"]["issues"]["items"]["properties"]["field"]["enum"]
        self.assertIn("question", allowed)
        self.assertNotIn("after", allowed)

    def test_server_attaches_exact_review_source_without_quote_matching(self):
        rejected = {"approved": False, "issues": [{"field": "question", "reason": "Уточните время наблюдения", "quote": "Пересказ вместо точной цитаты"}], "urgency": "continue"}
        client = FakeClient([tools_response(), output(question()), output(rejected), output(question()), output(REVIEW)])
        result = final(AgentService(settings(), client=client).clarify_events(adult()))
        self.assertEqual(result["mode"], "live")
        repair_input = json.loads(client.requests[3]["input"][0]["content"])
        self.assertEqual(repair_input["issues"][0]["quote"], question()["question"])


class TransportTests(unittest.TestCase):
    def test_provider_http_error_does_not_leak_response_or_key(self):
        client = ResponsesClient("secret-value", 1)
        with patch.object(client._opener, "open", side_effect=HTTPError("https://api.openai.com", 401, "unsafe secret-value", {}, None)):
            with self.assertRaises(AgentUnavailable) as caught:
                client.create({"store": False})
        self.assertEqual(str(caught.exception), "provider_http_401")
        self.assertNotIn("secret-value", str(caught.exception))

    def test_transport_endpoint_and_secret_are_server_side(self):
        client = ResponsesClient("secret-value", 2)
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"status":"completed","output":[]}'
        with patch.object(client._opener, "open", return_value=response) as opened:
            client.create({"store": False})
        request = opened.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.openai.com/v1/responses")
        self.assertEqual(request.get_header("Authorization"), "Bearer secret-value")
        self.assertEqual(opened.call_args.kwargs["timeout"], 2)


if __name__ == "__main__":
    unittest.main()
