import tempfile
import unittest
from pathlib import Path

import storage
from domain import DEMO_PROFILES, PROGRAMS, follow_up_date, recommend_from_profile


class CardRecommendationTests(unittest.TestCase):
    def test_card_data_selects_relevant_program_and_explains_it(self):
        cardio = recommend_from_profile(DEMO_PROFILES["demo_cardio"])
        woman = recommend_from_profile(DEMO_PROFILES["demo_woman"])
        senior = recommend_from_profile(DEMO_PROFILES["demo_senior"])
        self.assertEqual(cardio["checkup_id"], "heart")
        self.assertIn("давлении", " ".join(cardio["reasons"]))
        self.assertEqual(woman["checkup_id"], "female_basic")
        self.assertEqual(senior["checkup_id"], "female_extended_40")
        self.assertGreaterEqual(len(cardio["data_used"]), 5)

    def test_urgent_and_pregnancy_require_a_person(self):
        urgent = {**DEMO_PROFILES["demo_cardio"], "urgent": True}
        pregnancy = {**DEMO_PROFILES["demo_woman"], "pregnancy": True}
        self.assertNotIn("checkup_id", recommend_from_profile(urgent))
        self.assertNotIn("checkup_id", recommend_from_profile(pregnancy))

    def test_catalog_has_published_prices_and_six_month_contact_date(self):
        self.assertEqual(PROGRAMS["male_basic"]["price_tenge"], 355700)
        self.assertEqual(PROGRAMS["heart"]["price_tenge"], 257840)
        self.assertEqual(follow_up_date("2026-08-31"), "2027-02-28")


class BookingFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_db = storage.DB_PATH
        storage.DB_PATH = Path(self.temp.name) / "demo.sqlite3"
        storage.initialize()

    def tearDown(self):
        storage.DB_PATH = self.original_db
        self.temp.cleanup()

    def test_least_loaded_slot_booking_and_outcomes(self):
        slots = storage.get_slots("heart")
        self.assertGreater(len(slots), 0)
        self.assertEqual(slots, sorted(slots, key=lambda x: (x["estimated_wait_minutes"], x["start_at"])))
        initial = storage.get_metrics()
        booking = storage.create_booking("demo_cardio", "heart", slots[0]["start_at"], True)
        self.assertEqual(booking["status"], "reserved")
        with self.assertRaisesRegex(ValueError, "уже есть"):
            storage.create_booking("demo_cardio", "heart", slots[0]["start_at"], True)
        self.assertEqual(storage.get_metrics()["checkups_sold"], initial["checkups_sold"])
        booking = storage.complete_demo_booking(booking["id"], "demo_cardio")
        self.assertEqual(booking["status"], "completed")
        self.assertTrue(booking["follow_up_at"])
        storage.save_feedback(booking["id"], "demo_cardio", 5)
        final = storage.get_metrics()
        self.assertEqual(final["checkups_sold"], initial["checkups_sold"] + 1)
        self.assertEqual(final["sales_tenge"], initial["sales_tenge"] + PROGRAMS["heart"]["price_tenge"])
        self.assertEqual(final["repeat_visits"], initial["repeat_visits"] + 1)
        self.assertEqual(final["feedback_count"], initial["feedback_count"] + 1)


if __name__ == "__main__":
    unittest.main()
