"""Exercise privacy boundaries and honest clinic metric aggregation."""

from pathlib import Path
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
import sqlite3
import tempfile
import unittest

from metrics import MetricsStore


class MetricsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "metrics.sqlite3"
        self.store = MetricsStore(self.path)

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def test_empty_is_no_evidence_not_zero_real_sales(self):
        result = self.store.summary()
        self.assertEqual(sum(result["counts"].values()), 0)
        self.assertIsNone(result["sales"]["paid_sales"])
        self.assertIsNone(result["sales"]["booking_intents_per_recommendation"])
        self.assertIsNone(result["repeat_visits"]["confirmed_returns"])
        self.assertIsNone(result["time"]["clinic_visit_duration_ms"])
        self.assertIsNone(result["satisfaction"]["average_rating"])

    def test_aggregates_all_four_metrics_without_claiming_real_clinic_outcomes(self):
        for event in (
            {"event": "questionnaire_started", "mode": "adult"},
            {"event": "assistant_completed", "mode": "adult", "duration_ms": 1500},
            {"event": "recommendation_ready", "mode": "adult", "package_id": "heart", "duration_ms": 60000},
            {"event": "recommendation_ready", "mode": "child", "package_id": "child", "duration_ms": 30000},
            {"event": "booking_intent", "mode": "adult", "package_id": "heart"},
            {"event": "reminder_intent", "mode": "adult", "package_id": "heart"},
            {"event": "satisfaction_submitted", "mode": "adult", "rating": 5},
            {"event": "satisfaction_submitted", "mode": "child", "rating": 3},
        ):
            self.store.track(event)
        result = self.store.summary()
        self.assertEqual(result["sales"]["booking_intents_per_recommendation"], 0.5)
        self.assertEqual(result["time"]["flow"]["average_ms"], 45000)
        self.assertEqual(result["time"]["assistant"]["average_ms"], 1500)
        self.assertEqual(result["repeat_visits"]["reminder_intents"], 1)
        self.assertEqual(result["satisfaction"]["average_rating"], 4)
        self.assertEqual(result["satisfaction"]["positive_share"], 0.5)
        self.assertEqual(result["satisfaction"]["distribution"]["5"], 1)
        self.assertIsNone(result["sales"]["revenue_tenge"])

    def test_rejects_identifiers_medical_text_and_invalid_payload_types(self):
        safe = {"event": "questionnaire_started", "mode": "adult"}
        for extra in ("ip", "iin", "patient_id", "session_id", "notes", "answers", "user_agent", "timestamp"):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.store.track({**safe, extra: "private"})
        for payload in (None, [], "event", {"event": []}, {"event": "other", "mode": "adult"}, {**safe, "mode": []}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.store.track(payload)
        self.assertEqual(sum(self.store.summary()["counts"].values()), 0)

    def test_rejects_invalid_ratings_durations_and_cross_age_packages(self):
        invalid = [
            {"event": "satisfaction_submitted", "mode": "adult", "rating": value}
            for value in (True, 0, 6, 4.5, "5", None)
        ] + [
            {"event": "assistant_completed", "mode": "adult", "duration_ms": value}
            for value in (True, -1, 3_600_001, 1.5, "100", None)
        ] + [
            {"event": "booking_intent", "mode": "child", "package_id": "heart"},
            {"event": "booking_intent", "mode": "adult", "package_id": "child"},
            {"event": "booking_intent", "mode": "adult", "package_id": []},
            {"event": "recommendation_ready", "mode": "adult"},
            {"event": "questionnaire_started", "mode": "adult", "package_id": "heart"},
            {"event": "questionnaire_started", "mode": "adult", "rating": 5},
            {"event": "booking_intent", "mode": "adult", "package_id": "heart", "duration_ms": 50},
        ]
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.store.track(payload)

    def test_only_allowlisted_columns_are_persisted_and_data_survives_reopen(self):
        self.store.track({"event": "booking_intent", "mode": "adult", "package_id": "male_basic"})
        with closing(sqlite3.connect(self.path)) as connection:
            columns = [row[1] for row in connection.execute("PRAGMA table_info(events)")]
            self.assertEqual(columns, ["recorded_at", "event", "mode", "package_id", "duration_ms", "rating"])
        self.store.close()
        self.store = MetricsStore(self.path)
        self.assertEqual(self.store.summary()["counts"]["booking_intent"], 1)

    def test_expired_events_are_removed(self):
        self.store.track({"event": "questionnaire_started", "mode": "adult"})
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("UPDATE events SET recorded_at = '2000-01-01T00:00:00+00:00'")
            connection.commit()
        self.assertEqual(self.store.summary()["counts"]["questionnaire_started"], 0)

    def test_repeated_clicks_are_not_silently_claimed_as_unique_conversion(self):
        self.store.track({"event": "recommendation_ready", "mode": "adult", "package_id": "heart"})
        for _ in range(2):
            self.store.track({"event": "booking_intent", "mode": "adult", "package_id": "heart"})
        self.assertEqual(self.store.summary()["sales"]["booking_intents_per_recommendation"], 2)

    def test_threaded_server_requests_do_not_drop_events(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: self.store.track({"event": "questionnaire_started", "mode": "adult"}), range(32)))
        self.assertEqual(self.store.summary()["counts"]["questionnaire_started"], 32)


if __name__ == "__main__":
    unittest.main()
