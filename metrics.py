"""Anonymous, allowlisted product events. Never store medical answers or identities."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from threading import Lock


EVENTS = frozenset({
    "questionnaire_started", "assistant_completed", "recommendation_ready",
    "booking_intent", "reminder_intent", "satisfaction_submitted",
})
PACKAGE_IDS = frozenset({
    "male_basic", "female_basic", "male_extended_40", "female_extended_40",
    "heart", "child",
})
_FIELDS = frozenset({"event", "mode", "package_id", "duration_ms", "rating"})
_DURATION_EVENTS = frozenset({"assistant_completed", "recommendation_ready"})
_PACKAGE_EVENTS = frozenset({
    "recommendation_ready", "booking_intent", "reminder_intent", "satisfaction_submitted",
})


def _validate(event: dict) -> None:
    if not isinstance(event, dict) or set(event) - _FIELDS:
        raise ValueError("Событие содержит неподдерживаемые поля.")
    name = event.get("event")
    if not isinstance(name, str) or name not in EVENTS:
        raise ValueError("Неизвестный тип события.")
    mode = event.get("mode")
    if not isinstance(mode, str) or mode not in ("adult", "child"):
        raise ValueError("Укажите сценарий: для взрослого или ребёнка.")
    package = event.get("package_id")
    if "package_id" in event:
        if name not in _PACKAGE_EVENTS or not isinstance(package, str) or package not in PACKAGE_IDS:
            raise ValueError("Неизвестная программа для этого события.")
        if (package == "child") != (mode == "child"):
            raise ValueError("Программа не соответствует выбранному сценарию.")
    elif name in ("recommendation_ready", "booking_intent"):
        raise ValueError("Укажите программу.")
    if "duration_ms" in event:
        duration = event["duration_ms"]
        if name not in _DURATION_EVENTS or type(duration) is not int or not 0 <= duration <= 3_600_000:
            raise ValueError("Недопустимое время выполнения сценария.")
    if name == "satisfaction_submitted":
        rating = event.get("rating")
        if type(rating) is not int or not 1 <= rating <= 5:
            raise ValueError("Оценка должна быть целым числом от 1 до 5.")
    elif "rating" in event:
        raise ValueError("Оценка допустима только для события обратной связи.")


class MetricsStore:
    """One shared store per process; SQLite also serializes multiple processes.

    Ratios are event ratios, not unique-user conversion. No stable identifiers are
    accepted, so deduplication and paid-sales attribution deliberately do not exist.
    """

    def __init__(self, db_path: str | Path | None = None, *, retention_days: int = 90):
        if type(retention_days) is not int or not 1 <= retention_days <= 365:
            raise ValueError("Срок хранения метрик должен быть от 1 до 365 дней.")
        self.retention_days = retention_days
        path = str(db_path if db_path is not None else Path(__file__).parent / "data" / "metrics.sqlite3")
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._connection = sqlite3.connect(path, timeout=10, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=NORMAL")
        self._connection.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                recorded_at TEXT NOT NULL,
                event TEXT NOT NULL CHECK (event IN (
                    'questionnaire_started', 'assistant_completed', 'recommendation_ready',
                    'booking_intent', 'reminder_intent', 'satisfaction_submitted'
                )),
                mode TEXT NOT NULL CHECK (mode IN ('adult', 'child')),
                package_id TEXT CHECK (package_id IN (
                    'male_basic', 'female_basic', 'male_extended_40', 'female_extended_40', 'heart', 'child'
                )),
                duration_ms INTEGER CHECK (duration_ms >= 0 AND duration_ms <= 3600000),
                rating INTEGER CHECK (rating >= 1 AND rating <= 5)
            );
            CREATE INDEX IF NOT EXISTS events_recorded_at ON events(recorded_at);
            CREATE INDEX IF NOT EXISTS events_name ON events(event);
        """)
        with self._connection:
            self._purge()

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    def _purge(self) -> None:
        cutoff = (self._now() - timedelta(days=self.retention_days)).isoformat(timespec="seconds")
        self._connection.execute("DELETE FROM events WHERE recorded_at < ?", (cutoff,))

    def track(self, event: dict) -> None:
        _validate(event)
        with self._lock, self._connection:
            self._purge()
            self._connection.execute(
                "INSERT INTO events (recorded_at, event, mode, package_id, duration_ms, rating) VALUES (?, ?, ?, ?, ?, ?)",
                (self._now().isoformat(timespec="seconds"), event["event"], event["mode"],
                 event.get("package_id"), event.get("duration_ms"), event.get("rating")),
            )

    def summary(self) -> dict:
        with self._lock, self._connection:
            self._purge()
            rows = self._connection.execute("SELECT event, COUNT(*) AS count FROM events GROUP BY event").fetchall()
            counts = {name: 0 for name in sorted(EVENTS)}
            counts.update({row["event"]: row["count"] for row in rows})
            time_rows = self._connection.execute("""
                SELECT event, COUNT(duration_ms) AS samples, AVG(duration_ms) AS average_ms,
                       MIN(duration_ms) AS minimum_ms, MAX(duration_ms) AS maximum_ms
                FROM events WHERE duration_ms IS NOT NULL GROUP BY event
            """).fetchall()
            times = {name: {"samples": 0, "average_ms": None, "minimum_ms": None, "maximum_ms": None}
                     for name in sorted(_DURATION_EVENTS)}
            for row in time_rows:
                times[row["event"]] = {
                    "samples": row["samples"], "average_ms": round(row["average_ms"], 1),
                    "minimum_ms": row["minimum_ms"], "maximum_ms": row["maximum_ms"],
                }
            ratings = self._connection.execute("""
                SELECT COUNT(rating) AS samples, AVG(rating) AS average,
                       SUM(CASE WHEN rating >= 4 THEN 1 ELSE 0 END) AS positive
                FROM events WHERE event = 'satisfaction_submitted'
            """).fetchone()
            distribution = {str(value): 0 for value in range(1, 6)}
            distribution.update({str(row["rating"]): row["count"] for row in self._connection.execute(
                "SELECT rating, COUNT(*) AS count FROM events WHERE rating IS NOT NULL GROUP BY rating"
            )})
            packages = [dict(row) for row in self._connection.execute("""
                SELECT package_id,
                       SUM(CASE WHEN event = 'recommendation_ready' THEN 1 ELSE 0 END) AS recommendations,
                       SUM(CASE WHEN event = 'booking_intent' THEN 1 ELSE 0 END) AS booking_intents
                FROM events WHERE package_id IS NOT NULL GROUP BY package_id ORDER BY package_id
            """)]
            period = self._connection.execute("SELECT MIN(recorded_at) AS first_event_at, MAX(recorded_at) AS last_event_at FROM events").fetchone()
        recommendations = counts["recommendation_ready"]
        return {
            "generated_at": self._now().isoformat(timespec="seconds"),
            "retention_days": self.retention_days,
            "period": dict(period),
            "counts": counts,
            "sales": {
                "booking_intents": counts["booking_intent"],
                "booking_intents_per_recommendation": round(counts["booking_intent"] / recommendations, 4) if recommendations else None,
                "paid_sales": None,
                "revenue_tenge": None,
                "note": "Это интерес к записи. Оплаты и выручка не подключены; отношение событий не является конверсией уникальных пациентов.",
            },
            "time": {
                "flow": times["recommendation_ready"],
                "assistant": times["assistant_completed"],
                "clinic_visit_duration_ms": None,
                "note": "Измеряется время работы интерфейса. Фактическое время прохождения клиники ещё не измеряется.",
            },
            "repeat_visits": {
                "reminder_intents": counts["reminder_intent"],
                "reminder_intents_per_recommendation": round(counts["reminder_intent"] / recommendations, 4) if recommendations else None,
                "confirmed_returns": None,
                "note": "Создание напоминания не подтверждает повторный визит.",
            },
            "satisfaction": {
                "samples": ratings["samples"],
                "average_rating": round(ratings["average"], 2) if ratings["samples"] else None,
                "positive_share": round(ratings["positive"] / ratings["samples"], 4) if ratings["samples"] else None,
                "distribution": distribution,
                "note": "Добровольная оценка опыта работы с сервисом от 1 до 5; доля положительных оценок — ответы 4 и 5.",
            },
            "packages": packages,
            "limitations": [
                "Счётчики событий не содержат идентификаторов и не определяют число уникальных пациентов.",
                "Повторные события и автоматические запросы могут влиять на показатели.",
                "Демонстрационные действия не доказывают рост продаж, сокращение очередей или улучшение здоровья.",
            ],
        }

    def close(self) -> None:
        with self._lock:
            self._connection.close()
