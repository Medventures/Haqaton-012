import unittest
from datetime import date

from domain import PROGRAMS, add_months, recommend


class RecommendationTests(unittest.TestCase):
    def answers(self, **changes):
        value = {
            "age": 35, "sex": "female", "concerns": [], "family": [],
            "smoking": False, "low_activity": False, "chronic": False,
            "pregnancy": False, "urgent": False, "last_checkup": None,
        }
        value.update(changes)
        return value

    def test_age_and_sex_select_a_published_package(self):
        cases = [
            ("female", 39, "female_basic"),
            ("female", 40, "female_extended_40"),
            ("male", 39, "male_basic"),
            ("male", 40, "male_extended_40"),
        ]
        for sex, age, expected in cases:
            with self.subTest(sex=sex, age=age):
                result = recommend(self.answers(sex=sex, age=age), today=date(2026, 9, 30))
                self.assertEqual(result["checkup_id"], expected)
                self.assertEqual(result["name"], PROGRAMS[expected]["name"])
                self.assertEqual(len(result["route"]), 5)
                self.assertEqual(result["report"]["sections"][1]["status"], "Ожидаются")

    def test_heart_factors_have_explainable_reasons(self):
        result = recommend(self.answers(age=44, sex="male", smoking=True, family=["heart"]), today=date(2026, 9, 30))
        self.assertEqual(result["checkup_id"], "heart")
        self.assertIn("Вы указали курение", result["reasons"])
        self.assertIn("В семейной истории указаны сердечно-сосудистые заболевания", result["reasons"])
        self.assertEqual(result["reminder_date"], "2027-03-30")

    def test_medical_exceptions_stop_automatic_selection(self):
        self.assertEqual(recommend({"urgent": True})["status"], "urgent")
        self.assertEqual(recommend(self.answers(pregnancy=True))["status"], "consultation")

    def test_invalid_input_and_calendar_edge(self):
        with self.assertRaisesRegex(ValueError, "возраст"):
            recommend(self.answers(age=17))
        with self.assertRaisesRegex(ValueError, "(?i)дата"):
            recommend(self.answers(last_checkup="2099-01-01"))
        self.assertEqual(add_months(date(2026, 8, 31), 6), date(2027, 2, 28))

    def test_demo_packages_and_open_answer(self):
        result = recommend(self.answers(age=28, sex="male", notes="Недавно проходил ЭКГ", preferred_time="later"), today=date(2026, 9, 30))
        self.assertEqual(len(result["packages"]), 3)
        self.assertTrue(all(package["price_tenge"] < 100000 for package in result["packages"]))
        self.assertEqual(result["report"]["profile"]["notes"], "Недавно проходил ЭКГ")
        with self.assertRaisesRegex(ValueError, "500"):
            recommend(self.answers(notes="а" * 501))

    def test_parent_fills_child_questionnaire(self):
        for age in (0, 8, 17):
            with self.subTest(age=age):
                result = recommend({
                    "patient_type": "child", "age": age, "sex": "female",
                    "guardian_confirmed": True, "child_concerns": ["vision"],
                    "child_chronic": False, "notes": "Носит очки",
                }, today=date(2026, 9, 30))
                self.assertEqual(result["checkup_id"], "child")
                self.assertEqual(len(result["packages"]), 1)
                self.assertEqual(result["report"]["profile"]["concerns"][0], "вопросы о зрении")
                self.assertEqual(result["reminder_date"], "2026-10-30" if age == 0 else "2027-09-30")
        with self.assertRaisesRegex(ValueError, "родитель"):
            recommend({"patient_type": "child", "age": 8, "sex": "female", "guardian_confirmed": False})
        with self.assertRaisesRegex(ValueError, "17"):
            recommend({"patient_type": "child", "age": 18, "sex": "female", "guardian_confirmed": True})


if __name__ == "__main__":
    unittest.main()
