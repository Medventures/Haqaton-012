import unittest
from datetime import date

from assistant_logic import build_clarification, resolve_clarification
from domain import recommend


class ClarificationTests(unittest.TestCase):
    def adult(self, **changes):
        answers = {"patient_type": "adult", "age": 35, "sex": "male", "concerns": [], "notes": ""}
        answers.update(changes)
        return answers

    def child(self, **changes):
        answers = {"patient_type": "child", "age": 8, "sex": "female", "guardian_confirmed": True, "child_concerns": [], "notes": ""}
        answers.update(changes)
        return answers

    def test_pressure_and_fatigue_produce_specific_reproducible_question(self):
        answers = self.adult(concerns=["pressure", "fatigue"])
        question = build_clarification(answers)
        self.assertEqual(question, build_clarification(answers))
        self.assertEqual(question["id"], "pressure_context")
        self.assertIn("усталость", question["question"])
        self.assertEqual(len(question["signals"]), 2)
        self.assertEqual(len(question["options"]), 4)
        self.assertNotIn("action", question["options"][0])
        measured = resolve_clarification(answers, {"question_id": question["id"], "option_id": "changed", "detail": "145/90 вечером"})
        sensation = resolve_clarification(answers, {"question_id": question["id"], "option_id": "not_measured"})
        self.assertNotEqual(measured["route_note"], sensation["route_note"])
        self.assertIn("145/90 вечером", measured["clinician_note"])
        self.assertIn("не подтверждены", sensation["route_note"])

    def test_stale_and_forged_answers_are_rejected(self):
        answers = self.adult(concerns=["pressure"])
        for payload in (
            {"question_id": "visit_goal", "option_id": "changed"},
            {"question_id": "pressure_context", "option_id": "invented"},
            {"question_id": "pressure_context"},
            {"question_id": "pressure_context", "skipped": "false"},
            {"question_id": "pressure_context", "skipped": True, "option_id": "changed"},
        ):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                resolve_clarification(answers, payload)

    def test_skipping_never_invents_answer(self):
        result = resolve_clarification(self.adult(concerns=["pressure"]), {"question_id": "pressure_context", "skipped": True})
        self.assertTrue(result["skipped"])
        self.assertEqual(result["action"], "continue")
        self.assertEqual(result["answer_label"], "Уточнение пропущено")
        self.assertIn("без ответа", result["route_note"])

    def test_child_ignores_hidden_adult_fields(self):
        child = self.child(child_concerns=["vision"])
        contaminated = {**child, "concerns": ["heart", "pressure", "fatigue"], "smoking": True, "chronic": True, "pregnancy": True, "family": ["heart"]}
        self.assertEqual(build_clarification(child), build_clarification(contaminated))
        no_concerns = {**contaminated, "child_concerns": []}
        self.assertEqual(build_clarification(no_concerns)["id"], "visit_goal")
        self.assertEqual(build_clarification(self.child(child_chronic=True))["id"], "chronic_followup")

    def test_every_question_has_distinct_valid_options_and_resolves(self):
        cases = [
            (self.adult(concerns=["heart"]), "heart_context"),
            (self.adult(concerns=["pressure"]), "pressure_context"),
            (self.adult(concerns=["fatigue"]), "fatigue_pattern"),
            (self.adult(notes="Сохранилось ЭКГ"), "recent_records"),
            (self.adult(notes="Аллергии на лекарства нет"), "medicines_context"),
            (self.adult(chronic=True), "chronic_followup"),
            (self.child(child_concerns=["vision"]), "child_vision"),
            (self.child(child_concerns=["sleep"]), "child_sleep"),
            (self.child(child_concerns=["development"]), "child_development"),
            (self.adult(), "visit_goal"),
        ]
        for answers, expected in cases:
            with self.subTest(expected=expected):
                question = build_clarification(answers)
                self.assertEqual(question["id"], expected)
                ids = [option["id"] for option in question["options"]]
                self.assertEqual(len(ids), len(set(ids)))
                for option_id in ids:
                    result = resolve_clarification(answers, {"question_id": expected, "option_id": option_id})
                    self.assertIn(result["action"], ("continue", "consultation", "urgent"))
                    self.assertTrue(result["impact"])
                    self.assertTrue(result["clinician_note"])
                    self.assertTrue(result["route_note"])

    def test_detail_boundaries_and_types(self):
        answers = self.adult()
        payload = {"question_id": "visit_goal", "option_id": "concern", "detail": "а" * 500}
        self.assertEqual(len(resolve_clarification(answers, payload)["detail"]), 500)
        for detail in ("а" * 501, None, 123, {"text": "жалоба"}):
            with self.subTest(detail_type=type(detail).__name__), self.assertRaises(ValueError):
                resolve_clarification(answers, {**payload, "detail": detail})
        with self.assertRaises(ValueError):
            build_clarification(self.adult(notes="а" * 501))

    def test_acute_answer_stops_routine_plan(self):
        result = resolve_clarification(self.adult(concerns=["heart"]), {"question_id": "heart_context", "option_id": "symptoms_now"})
        self.assertEqual(result["action"], "urgent")
        self.assertIn("срочной", result["impact"])
        # A description is preserved for the clinician, not converted to a diagnosis.
        detail = "Тревожит самочувствие; не знаю причину"
        result = resolve_clarification(self.adult(), {"question_id": "visit_goal", "option_id": "concern", "detail": detail})
        self.assertEqual(result["detail"], detail)
        self.assertEqual(result["action"], "continue")


class RecommendationClarificationTests(unittest.TestCase):
    def adult(self, **changes):
        answers = {"patient_type": "adult", "age": 35, "sex": "male", "concerns": ["pressure", "fatigue"], "notes": ""}
        answers.update(changes)
        return answers

    def child(self, **changes):
        answers = {"patient_type": "child", "age": 8, "sex": "female", "guardian_confirmed": True, "child_concerns": ["vision"], "notes": ""}
        answers.update(changes)
        return answers

    def recommendation(self, answers):
        return recommend(answers, today=date(2026, 9, 30))

    def test_answer_follows_adult_into_report_and_every_package_route(self):
        answers = self.adult(clarification={
            "question_id": "pressure_context", "option_id": "changed", "detail": "145/90 вечером",
        })
        result = self.recommendation(answers)
        self.assertEqual(result["status"], "recommended")
        clarification = result["clarification"]
        self.assertEqual(result["report"]["clarification"], clarification)
        self.assertIn("145/90 вечером", clarification["clinician_note"])
        self.assertIn(clarification["route_note"], result["route"][0]["detail"])
        for package in result["packages"]:
            with self.subTest(package=package["id"]):
                self.assertIn(clarification["route_note"], package["route"][0]["detail"])

    def test_child_answer_is_attached_to_pediatrician_not_reception(self):
        answers = self.child(clarification={"question_id": "child_vision", "option_id": "glasses"})
        result = self.recommendation(answers)
        note = result["clarification"]["route_note"]
        self.assertEqual(result["report"]["clarification"], result["clarification"])
        self.assertNotIn(note, result["route"][0]["detail"])
        self.assertIn(note, result["route"][1]["detail"])
        for package in result["packages"]:
            self.assertIn(note, package["route"][1]["detail"])

    def test_skip_preserves_route_and_reasons(self):
        answers = self.adult()
        baseline = self.recommendation(answers)
        result = self.recommendation({**answers, "clarification": {"question_id": "pressure_context", "skipped": True}})
        self.assertTrue(result["clarification"]["skipped"])
        self.assertEqual(result["route"], baseline["route"])
        self.assertEqual(result["reasons"], baseline["reasons"])
        self.assertEqual(result["packages"], baseline["packages"])

    def test_clinical_exceptions_hide_packages_and_report(self):
        cases = [
            (self.adult(concerns=["heart"]), "heart_context", "symptoms_now", "urgent"),
            (self.adult(concerns=["heart"]), "heart_context", "episodes", "consultation"),
            (self.child(child_concerns=["sleep"]), "child_sleep", "breathing", "consultation"),
            (self.child(child_concerns=["development"]), "child_development", "lost_skill", "consultation"),
        ]
        for answers, question_id, option_id, expected in cases:
            with self.subTest(question_id=question_id, option_id=option_id):
                result = self.recommendation({**answers, "clarification": {"question_id": question_id, "option_id": option_id}})
                self.assertEqual(result["status"], expected)
                self.assertEqual(result["clarification"]["action"], expected)
                self.assertTrue(result["title"])
                self.assertTrue(result["message"])
                self.assertNotIn("packages", result)
                self.assertNotIn("report", result)

    def test_original_safety_gates_run_before_clarification(self):
        urgent = self.recommendation({"urgent": True, "clarification": {"question_id": "forged"}})
        self.assertEqual(urgent["status"], "urgent")
        pregnancy = self.recommendation(self.adult(sex="female", pregnancy=True, clarification={"question_id": "forged"}))
        self.assertEqual(pregnancy["status"], "consultation")

    def test_recommend_rejects_forged_clarification(self):
        for answer in (
            {"question_id": "visit_goal", "option_id": "prevention"},
            {"question_id": "pressure_context", "option_id": "forged"},
        ):
            with self.subTest(answer=answer), self.assertRaises(ValueError):
                self.recommendation(self.adult(clarification=answer))


if __name__ == "__main__":
    unittest.main()
