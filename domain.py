"""Public package catalogue and synthetic health records for the hackathon demo."""

from __future__ import annotations

from datetime import date, datetime


PRICE_SOURCE = "https://primegc.kz/price-list-strahovie/"
PROGRAMS = {
    "male_basic": {
        "name": "Мужской базовый до 40 лет",
        "price_tenge": 355700,
        "audience": "Мужчинам до 40 лет",
        "summary": "Консультации, лабораторные анализы и исследования мужского здоровья.",
        "features": ["Врач-куратор и профильные специалисты", "Анализы крови и мочи", "ЭКГ, УЗИ и исследования по программе"],
        "duration_hours": "5–6 часов",
    },
    "female_basic": {
        "name": "Женский базовый до 40 лет",
        "price_tenge": 358020,
        "audience": "Женщинам до 40 лет",
        "summary": "Консультации, анализы и исследования женского здоровья.",
        "features": ["Врач-куратор и гинеколог", "Анализы крови и мочи", "ЭКГ, УЗИ и исследования по программе"],
        "duration_hours": "5–6 часов",
    },
    "male_extended_40": {
        "name": "Мужской расширенный после 40 лет",
        "price_tenge": 467100,
        "audience": "Мужчинам от 40 лет",
        "summary": "Расширенная программа с дополнительными обследованиями.",
        "features": ["Врач-куратор и профильные специалисты", "Расширенные анализы", "ЭКГ, УЗИ и исследования по программе"],
        "duration_hours": "6–7 часов",
    },
    "female_extended_40": {
        "name": "Женский расширенный после 40 лет",
        "price_tenge": 479900,
        "audience": "Женщинам от 40 лет",
        "summary": "Расширенная программа с дополнительными обследованиями.",
        "features": ["Врач-куратор и гинеколог", "Расширенные анализы", "ЭКГ, УЗИ и исследования по программе"],
        "duration_hours": "6–7 часов",
    },
    "heart": {
        "name": "Чекап «Сердце»",
        "price_tenge": 257840,
        "audience": "Акцент на сердце и сосуды",
        "summary": "Программа для оценки состояния сердечно-сосудистой системы.",
        "features": ["Врач-куратор", "Липидный профиль и другие анализы", "ЭКГ, ЭхоКГ и исследования сосудов"],
        "duration_hours": "5–6 часов",
    },
}

STANDARD_ROUTE = [
    {"offset_minutes": 0, "title": "Встреча с врачом-куратором", "detail": "Врач проверяет карту и подтверждает программу."},
    {"offset_minutes": 40, "title": "Лабораторные анализы", "detail": "Сдача анализов с учётом подготовки."},
    {"offset_minutes": 100, "title": "Исследования", "detail": "ЭКГ, УЗИ и другие процедуры по программе."},
    {"offset_minutes": 240, "title": "Приёмы специалистов", "detail": "Консультации согласно согласованному маршруту."},
    {"offset_minutes": 330, "title": "Завершение основного дня", "detail": "Разбор результатов проходит после их готовности."},
]
HEART_ROUTE = [
    *STANDARD_ROUTE[:3],
    {"offset_minutes": 240, "title": "Исследования сердца и сосудов", "detail": "ЭхоКГ и другие исследования по назначению врача."},
    {"offset_minutes": 330, "title": "Завершение основного дня", "detail": "Суточное наблюдение, если оно назначено, продолжится после визита."},
]
for _id, _program in PROGRAMS.items():
    _program["route"] = HEART_ROUTE if _id == "heart" else STANDARD_ROUTE

# These are invented, non-identifying records. They must never be presented as
# records imported from DamuMed or the clinic information system.
DEMO_PROFILES = {
    "demo_cardio": {
        "id": "demo_cardio", "display_name": "Алексей, 43 года", "age": 43, "sex": "male",
        "source": "Демонстрационная карта", "last_checkup": "2025-11-18",
        "conditions": ["Повышенное артериальное давление"],
        "medications": ["Лекарство для контроля давления по назначению врача"],
        "allergies": ["Не указаны"], "family_history": ["Заболевания сердца и сосудов"],
        "lifestyle": ["Низкая физическая активность"],
        "observations": [
            {"name": "Артериальное давление", "value": "145/90 мм рт. ст.", "date": "2026-08-12", "code": "blood_pressure", "numeric": 145},
            {"name": "Холестерин ЛПНП", "value": "3,6 ммоль/л", "date": "2026-08-12", "code": "ldl", "numeric": 3.6},
        ],
        "history": [
            {"date": "2025-11-18", "title": "Профилактический осмотр", "detail": "Результаты сохранены в карте"},
            {"date": "2026-08-12", "title": "Контроль показателей", "detail": "Давление и липидный профиль"},
        ],
    },
    "demo_woman": {
        "id": "demo_woman", "display_name": "Мадина, 36 лет", "age": 36, "sex": "female",
        "source": "Демонстрационная карта", "last_checkup": "2024-09-03",
        "conditions": [], "medications": [], "allergies": ["Не указаны"],
        "family_history": ["Сахарный диабет"], "lifestyle": [],
        "observations": [
            {"name": "Ферритин", "value": "18 мкг/л", "date": "2026-07-22", "code": "ferritin", "numeric": 18},
            {"name": "Гемоглобин", "value": "123 г/л", "date": "2026-07-22", "code": "hemoglobin", "numeric": 123},
        ],
        "history": [
            {"date": "2024-09-03", "title": "Профилактический осмотр", "detail": "Заключение врача сохранено"},
            {"date": "2026-07-22", "title": "Лабораторные анализы", "detail": "Показатели крови"},
        ],
    },
    "demo_senior": {
        "id": "demo_senior", "display_name": "Алия, 51 год", "age": 51, "sex": "female",
        "source": "Демонстрационная карта", "last_checkup": "2025-01-10",
        "conditions": ["Сахарный диабет 2 типа"], "medications": ["Лечение по назначению врача"],
        "allergies": ["Не указаны"], "family_history": [], "lifestyle": [],
        "observations": [
            {"name": "Глюкоза крови", "value": "6,8 ммоль/л", "date": "2026-08-05", "code": "glucose", "numeric": 6.8},
            {"name": "Артериальное давление", "value": "128/82 мм рт. ст.", "date": "2026-08-05", "code": "blood_pressure", "numeric": 128},
        ],
        "history": [
            {"date": "2025-01-10", "title": "Профилактический осмотр", "detail": "Заключение врача сохранено"},
            {"date": "2026-08-05", "title": "Контроль показателей", "detail": "Глюкоза и давление"},
        ],
    },
}


def get_profile(profile_id: str) -> dict:
    try:
        return DEMO_PROFILES[profile_id]
    except KeyError as exc:
        raise ValueError("Карта не найдена. Выберите демонстрационный профиль.") from exc


def recommend_from_profile(profile: dict) -> dict:
    """Use longitudinal record fields, not questionnaire answers or package prices."""
    age, sex = profile["age"], profile["sex"]
    if profile.get("urgent"):
        return {"status": "urgent", "title": "Сначала обратитесь за медицинской помощью", "message": "При сильной боли в груди, выраженной одышке или внезапном ухудшении самочувствия не ждите чекапа. Обратитесь за срочной медицинской помощью."}
    if profile.get("pregnancy"):
        return {"status": "consultation", "title": "Программу нужно согласовать с врачом", "message": "Во время беременности состав обследований подбирают индивидуально. Свяжитесь с клиникой перед записью."}
    if not isinstance(age, int) or not 18 <= age <= 100 or sex not in ("male", "female"):
        raise ValueError("В карте не хватает данных для автоматического подбора. Обратитесь к врачу-куратору.")

    pressure = next((x for x in profile.get("observations", []) if x.get("code") == "blood_pressure"), None)
    elevated_pressure = bool(pressure and isinstance(pressure.get("numeric"), (int, float)) and pressure["numeric"] >= 140)
    heart_condition = any("давлен" in item.lower() or "сердц" in item.lower() for item in profile.get("conditions", []))
    heart_focus = elevated_pressure or heart_condition
    basic_id = f"{sex}_{'extended_40' if age >= 40 else 'basic'}"
    selected_id = "heart" if heart_focus else basic_id
    reasons = [f"В карте указан возраст: {age} лет", "Программа учитывает мужское здоровье" if sex == "male" else "Программа учитывает женское здоровье"]
    if elevated_pressure:
        reasons.append(f"В карте есть запись о давлении: {pressure['value']}")
    if heart_condition:
        reasons.append("В карте указано наблюдение по поводу артериального давления или сердца")
    if profile.get("family_history"):
        reasons.append("Учтена семейная история: " + ", ".join(profile["family_history"]).lower())
    if profile.get("lifestyle"):
        reasons.append("Учтены сведения об образе жизни: " + ", ".join(profile["lifestyle"]).lower())
    if profile.get("conditions") and not heart_condition:
        reasons.append("Учтены ранее указанные хронические заболевания")
    if profile.get("medications"):
        reasons.append("Врач должен сверить программу с принимаемыми лекарствами")
    if any(item != "Не указаны" for item in profile.get("allergies", [])):
        reasons.append("Перед процедурами врач должен учесть указанные аллергии")
    last = profile.get("last_checkup")
    if last:
        reasons.append("Последний профилактический осмотр в карте: " + datetime.strptime(last, "%Y-%m-%d").strftime("%d.%m.%Y"))

    alternatives = [basic_id] if selected_id == "heart" else (["heart"] if age >= 40 else [])
    return {
        "status": "recommended", "checkup_id": selected_id,
        "reasons": reasons, "profile_id": profile["id"],
        "data_used": ["Возраст и пол", "История посещений", "Известные заболевания", "Лекарства", "Аллергии", "Семейная история", "Образ жизни", "Последние показатели"],
        "alternatives": alternatives,
        "note": "Подбор предварительный. Врач проверит карту, состав обследований и подготовку. Сервис не ставит диагноз.",
    }


def follow_up_date(visit_date: str) -> str:
    """A six-month contact reminder, never an automatic medical prescription."""
    year, month, day = map(int, visit_date[:10].split("-"))
    month += 6
    if month > 12:
        year, month = year + 1, month - 12
    while day > 28:
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            day -= 1
    return date(year, month, day).isoformat()
