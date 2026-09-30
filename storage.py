"""Local demo calendar, booking ledger and measurable clinic outcomes."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

from domain import PROGRAMS, follow_up_date


DB_PATH = Path(__file__).resolve().parent / "demo.sqlite3"
_lock = threading.Lock()


@contextmanager
def connect():
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize() -> None:
    with _lock, connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS recommendations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id TEXT NOT NULL,
            program_id TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id TEXT NOT NULL,
            program_id TEXT NOT NULL,
            visit_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'reserved',
            paid INTEGER NOT NULL DEFAULT 0,
            checked_in_at TEXT,
            completed_at TEXT,
            satisfaction INTEGER,
            is_repeat INTEGER NOT NULL DEFAULT 0,
            follow_up_at TEXT
        )""")
        if db.execute("SELECT COUNT(*) FROM recommendations").fetchone()[0] == 0:
            seed_demo_data(db)
        db.commit()


def seed_demo_data(db: sqlite3.Connection) -> None:
    """Synthetic historical data makes every KPI inspectable in the demo."""
    now = datetime.now().replace(microsecond=0)
    for index in range(48):
        stamp = now - timedelta(days=index % 27, hours=index % 8)
        db.execute("INSERT INTO recommendations(profile_id,program_id,created_at) VALUES(?,?,?)",
                   (f"история-{index}", "male_basic" if index % 2 else "female_extended_40", stamp.isoformat()))
    program_ids = list(PROGRAMS)
    for index in range(14):
        day = now - timedelta(days=1 + index * 2)
        visit = day.replace(hour=8, minute=30)
        completed = index < 11
        paid = index < 12
        start = visit + timedelta(minutes=7)
        end = start + timedelta(minutes=285 + (index % 4) * 25)
        db.execute("""INSERT INTO bookings(
            profile_id,program_id,visit_at,created_at,status,paid,checked_in_at,
            completed_at,satisfaction,is_repeat,follow_up_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (
            f"история-{index}", program_ids[index % len(program_ids)], visit.isoformat(),
            (visit - timedelta(days=4)).isoformat(), "completed" if completed else "reserved",
            int(paid), start.isoformat() if completed else None,
            end.isoformat() if completed else None, 4 + index % 2 if index < 9 else None,
            int(index % 3 == 0), follow_up_date(visit.date().isoformat()) if completed else None,
        ))


def record_recommendation(profile_id: str, program_id: str) -> None:
    with _lock, connect() as db:
        db.execute("INSERT INTO recommendations(profile_id,program_id,created_at) VALUES(?,?,?)",
                   (profile_id, program_id, datetime.now().isoformat(timespec="seconds")))
        db.commit()


def _candidate_slots() -> list[dict]:
    today = date.today()
    slots = []
    for offset in range(1, 15):
        day = today + timedelta(days=offset)
        if day.weekday() == 6:
            continue
        hours = (8, 9, 10) if day.weekday() < 5 else (9, 10)
        for hour in hours:
            stamp = datetime.combine(day, datetime.min.time()).replace(hour=hour, minute=0)
            baseline = (day.toordinal() + hour) % 3
            slots.append({"start_at": stamp.isoformat(timespec="minutes"), "baseline": baseline})
    return slots


def get_slots(program_id: str) -> list[dict]:
    if program_id not in PROGRAMS:
        raise ValueError("Выбранная программа не найдена.")
    with connect() as db:
        rows = db.execute("SELECT visit_at,COUNT(*) AS count FROM bookings WHERE status='reserved' AND visit_at >= ? GROUP BY visit_at",
                          (datetime.now().isoformat(timespec="minutes"),)).fetchall()
    booked = {row["visit_at"][:16]: row["count"] for row in rows}
    options = []
    for item in _candidate_slots():
        occupancy = item["baseline"] + booked.get(item["start_at"], 0)
        if occupancy >= 3:
            continue
        wait = 5 + occupancy * 10
        options.append({"start_at": item["start_at"], "estimated_wait_minutes": wait,
                        "occupancy": occupancy, "capacity": 3,
                        "load_label": "Мало посетителей" if occupancy == 0 else "Умеренная загрузка" if occupancy == 1 else "Места почти заняты"})
    options.sort(key=lambda item: (item["estimated_wait_minutes"], item["start_at"]))
    return options[:8]


def create_booking(profile_id: str, program_id: str, start_at: str, is_repeat: bool) -> dict:
    if program_id not in PROGRAMS:
        raise ValueError("Выбранная программа не найдена.")
    candidate = next((item for item in _candidate_slots() if item["start_at"] == start_at), None)
    if candidate is None:
        raise ValueError("Это время уже недоступно. Выберите другое.")
    with _lock, connect() as db:
        db.execute("BEGIN IMMEDIATE")
        previous = db.execute("SELECT id FROM bookings WHERE profile_id=? AND status='reserved' AND visit_at >= ?",
                              (profile_id, datetime.now().isoformat(timespec="minutes"))).fetchone()
        if previous:
            raise ValueError("У вас уже есть демонстрационная запись. Её можно посмотреть ниже.")
        reserved = db.execute("SELECT COUNT(*) FROM bookings WHERE visit_at=? AND status='reserved'", (start_at,)).fetchone()[0]
        if candidate["baseline"] + reserved >= 3:
            raise ValueError("Это время уже занято. Выберите другое.")
        cursor = db.execute("""INSERT INTO bookings(profile_id,program_id,visit_at,created_at,is_repeat)
            VALUES(?,?,?,?,?)""", (profile_id, program_id, start_at,
            datetime.now().isoformat(timespec="seconds"), int(is_repeat)))
        booking_id = cursor.lastrowid
        db.commit()
    return get_booking(booking_id)


def get_booking(booking_id: int) -> dict:
    with connect() as db:
        row = db.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
    if row is None:
        raise ValueError("Запись не найдена.")
    return dict(row)


def get_profile_booking(profile_id: str) -> dict | None:
    with connect() as db:
        row = db.execute("SELECT * FROM bookings WHERE profile_id=? ORDER BY id DESC LIMIT 1", (profile_id,)).fetchone()
    return dict(row) if row else None


def complete_demo_booking(booking_id: int, profile_id: str) -> dict:
    with _lock, connect() as db:
        row = db.execute("SELECT * FROM bookings WHERE id=? AND profile_id=?", (booking_id, profile_id)).fetchone()
        if not row:
            raise ValueError("Запись не найдена.")
        if row["status"] == "completed":
            return dict(row)
        start = datetime.fromisoformat(row["visit_at"]) + timedelta(minutes=8)
        finish = start + timedelta(minutes=315)
        db.execute("""UPDATE bookings SET status='completed',paid=1,checked_in_at=?,completed_at=?,follow_up_at=? WHERE id=?""",
                   (start.isoformat(timespec="seconds"), finish.isoformat(timespec="seconds"),
                    follow_up_date(row["visit_at"][:10]), booking_id))
        db.commit()
    return get_booking(booking_id)


def save_feedback(booking_id: int, profile_id: str, score: int) -> dict:
    if isinstance(score, bool) or not isinstance(score, int) or not 1 <= score <= 5:
        raise ValueError("Выберите оценку от 1 до 5.")
    with _lock, connect() as db:
        row = db.execute("SELECT status FROM bookings WHERE id=? AND profile_id=?", (booking_id, profile_id)).fetchone()
        if not row or row["status"] != "completed":
            raise ValueError("Оценку можно оставить после посещения.")
        db.execute("UPDATE bookings SET satisfaction=? WHERE id=?", (score, booking_id))
        db.commit()
    return get_booking(booking_id)


def get_metrics() -> dict:
    cutoff = (datetime.now() - timedelta(days=30)).isoformat(timespec="seconds")
    with connect() as db:
        recommendations = db.execute("SELECT COUNT(*) FROM recommendations WHERE created_at>=?", (cutoff,)).fetchone()[0]
        rows = db.execute("SELECT * FROM bookings WHERE created_at>=?", (cutoff,)).fetchall()
    bookings = [dict(row) for row in rows]
    paid = [row for row in bookings if row["paid"]]
    completed = [row for row in bookings if row["completed_at"] and row["checked_in_at"]]
    durations = [(datetime.fromisoformat(row["completed_at"]) - datetime.fromisoformat(row["checked_in_at"])).total_seconds() / 60 for row in completed]
    scores = [row["satisfaction"] for row in bookings if row["satisfaction"]]
    return {
        "period": "Последние 30 дней", "demo": True,
        "recommendations": recommendations,
        "bookings": len(bookings),
        "booking_conversion_percent": round(len(bookings) * 100 / recommendations, 1) if recommendations else 0,
        "checkups_sold": len(paid),
        "sales_tenge": sum(PROGRAMS[row["program_id"]]["price_tenge"] for row in paid),
        "average_visit_minutes": round(sum(durations) / len(durations)) if durations else 0,
        "repeat_visits": sum(1 for row in completed if row["is_repeat"]),
        "average_satisfaction": round(sum(scores) / len(scores), 1) if scores else 0,
        "feedback_count": len(scores),
    }
