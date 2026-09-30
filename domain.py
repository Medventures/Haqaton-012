"""Rule-based check-up selection for the Russian-language MVP."""

from __future__ import annotations

from datetime import date
from assistant_logic import build_clarification, resolve_clarification


PROGRAMS = {
    "male_basic": {
        "name": "Мужской базовый до 40 лет",
        "audience": "Мужчинам до 40 лет",
        "price_tenge": 59900,
        "duration_hours": "5–6 часов",
        "summary": "Базовая программа с консультациями, анализами и исследованиями.",
        "includes": ["Врач-куратор и профильные специалисты", "Лабораторные анализы", "ЭКГ, УЗИ и исследования по программе"],
    },
    "female_basic": {
        "name": "Женский базовый до 40 лет",
        "audience": "Женщинам до 40 лет",
        "price_tenge": 59900,
        "duration_hours": "5–6 часов",
        "summary": "Базовая программа с консультациями, анализами и исследованиями.",
        "includes": ["Врач-куратор и гинеколог", "Лабораторные анализы", "ЭКГ, УЗИ и исследования по программе"],
    },
    "male_extended_40": {
        "name": "Мужской расширенный от 40 лет",
        "audience": "Мужчинам от 40 лет",
        "price_tenge": 89900,
        "duration_hours": "6–7 часов",
        "summary": "Расширенная программа с дополнительными обследованиями.",
        "includes": ["Врач-куратор и профильные специалисты", "Расширенные анализы", "ЭКГ, УЗИ и исследования по программе"],
    },
    "female_extended_40": {
        "name": "Женский расширенный от 40 лет",
        "audience": "Женщинам от 40 лет",
        "price_tenge": 89900,
        "duration_hours": "6–7 часов",
        "summary": "Расширенная программа с дополнительными обследованиями.",
        "includes": ["Врач-куратор и гинеколог", "Расширенные анализы", "ЭКГ, УЗИ и исследования по программе"],
    },
    "heart": {
        "name": "Check-up «Сердце»",
        "audience": "Программа с акцентом на сердце и сосуды",
        "price_tenge": 69900,
        "duration_hours": "4–5 часов",
        "summary": "Программа для оценки состояния сердечно-сосудистой системы.",
        "includes": ["Врач-куратор", "Анализы, включая липидный профиль", "ЭКГ, ЭхоКГ и исследования сосудов"],
    },
    "child": {
        "name": "Детский check-up PRIME",
        "audience": "Детям до 18 лет, по анкете родителя",
        "price_tenge": 49900,
        "duration_hours": "2–3 часа",
        "summary": "Профилактический осмотр ребёнка с педиатром.",
        "includes": ["Осмотр педиатра", "Оценка роста и развития", "Обсуждение истории прививок и дальнейших шагов"],
    },
}

CONCERNS = {
    "fatigue": "усталость",
    "pressure": "изменения давления",
    "heart": "вопросы о здоровье сердца",
    "digestion": "жалобы на пищеварение",
    "other": "другие жалобы",
}
FAMILY_HISTORY = {
    "heart": "сердечно-сосудистые заболевания",
    "diabetes": "сахарный диабет",
    "cancer": "онкологические заболевания",
}
CHILD_CONCERNS = {
    "development": "вопросы о росте и развитии",
    "vision": "вопросы о зрении",
    "hearing": "вопросы о слухе",
    "sleep": "вопросы о сне",
    "frequent_illness": "частые болезни",
    "other": "другие вопросы о здоровье",
}


def add_months(value: date, count: int) -> date:
    """Keep reminders on a valid calendar day, including February."""
    month_index = value.year * 12 + value.month - 1 + count
    year, month = divmod(month_index, 12)
    month += 1
    for day in range(value.day, 27, -1):
        try:
            return date(year, month, day)
        except ValueError:
            pass
    return date(year, month, min(value.day, 26))


def age_in_words(age: int) -> str:
    if age % 100 in (11, 12, 13, 14):
        ending = "лет"
    else:
        ending = {1: "год", 2: "года", 3: "года", 4: "года"}.get(age % 10, "лет")
    return f"{age} {ending}"


def _validate_answers(answers: dict) -> None:
    if not isinstance(answers, dict):
        raise ValueError("Проверьте ответы в анкете.")
    if answers.get("urgent") is True:
        return
    patient_type = answers.get("patient_type", "adult")
    if patient_type not in ("adult", "child"):
        raise ValueError("Выберите, для кого нужна программа.")
    age = answers.get("age")
    if isinstance(age, bool) or not isinstance(age, int) or not (0 <= age <= 17 if patient_type == "child" else 18 <= age <= 100):
        raise ValueError("Укажите возраст ребёнка от 0 до 17 лет." if patient_type == "child" else "Укажите возраст от 18 до 100 лет.")
    if answers.get("sex") not in ("male", "female"):
        raise ValueError("Выберите пол ребёнка." if patient_type == "child" else "Выберите пол для подбора программы.")
    if patient_type == "child" and answers.get("guardian_confirmed") is not True:
        raise ValueError("Анкету ребёнка должен заполнить родитель или законный представитель.")
    notes = answers.get("notes", "")
    if not isinstance(notes, str) or len(notes) > 500:
        raise ValueError("Дополнительный ответ должен быть короче 500 символов.")
    preferred_time = answers.get("preferred_time", "any")
    if preferred_time not in ("any", "morning", "later"):
        raise ValueError("Выберите удобное время посещения.")
    fields = (("child_concerns", CHILD_CONCERNS),) if patient_type == "child" else (("concerns", CONCERNS), ("family", FAMILY_HISTORY))
    for field, allowed in fields:
        values = answers.get(field, [])
        if not isinstance(values, list) or any(not isinstance(item, str) or item not in allowed for item in values):
            raise ValueError("Проверьте выбранные ответы в анкете.")
    boolean_fields = ("child_chronic", "urgent") if patient_type == "child" else ("smoking", "low_activity", "chronic", "pregnancy", "urgent")
    for field in boolean_fields:
        if not isinstance(answers.get(field, False), bool):
            raise ValueError("Проверьте ответы в анкете.")
    last_checkup = answers.get("last_checkup")
    if last_checkup:
        try:
            parsed = date.fromisoformat(last_checkup)
        except (TypeError, ValueError) as exc:
            raise ValueError("Проверьте дату последнего check-up.") from exc
        if parsed > date.today():
            raise ValueError("Дата последнего check-up не может быть в будущем.")


def _route(program_id: str) -> list[dict]:
    if program_id == "child":
        return [
            {"time": "09:00", "title": "Встреча родителя и ребёнка", "detail": "Сотрудник клиники уточнит данные анкеты."},
            {"time": "09:30", "title": "Осмотр педиатра", "detail": "Врач обсудит развитие, самочувствие и историю прививок."},
            {"time": "10:30", "title": "Дополнительные шаги", "detail": "Если потребуется, педиатр назначит исследования или консультации."},
            {"time": "11:30", "title": "План для семьи", "detail": "Педиатр объяснит результаты осмотра и дальнейшие действия."},
        ]
    route = [
        {"time": "08:30", "title": "Встреча с врачом-куратором", "detail": "Врач уточняет ответы и подтверждает план."},
        {"time": "09:15", "title": "Лабораторные анализы", "detail": "Сдача анализов по выбранной программе."},
        {"time": "10:30", "title": "Исследования", "detail": "ЭКГ, УЗИ и другие исследования по расписанию."},
        {"time": "13:00", "title": "Консультации специалистов", "detail": "Приёмы, включённые в программу."},
        {"time": "14:30", "title": "Завершение маршрута", "detail": "Врач объяснит дальнейшие шаги. Результаты обсудят после их готовности."},
    ]
    if program_id == "heart":
        route[3] = {"time": "13:00", "title": "Исследования сердца и сосудов", "detail": "Порядок определит врач-куратор."}
        route[4]["detail"] = "Суточное наблюдение, если назначено, продолжится после первого дня."
    return route


def clarify(answers: dict) -> dict:
    """Ask one contextual question after validating the original questionnaire."""
    _validate_answers(answers)
    if answers.get("urgent") or (answers.get("patient_type", "adult") == "adult" and answers.get("sex") == "female" and answers.get("pregnancy")):
        return {"status": "skip"}
    return build_clarification(answers)


def recommend(answers: dict, *, today: date | None = None) -> dict:
    result = _recommend_base(answers, today=today)
    if result["status"] != "recommended" or "clarification" not in answers:
        return result
    clarification = resolve_clarification(answers, answers["clarification"])
    if clarification["action"] in ("urgent", "consultation"):
        return {
            "status": clarification["action"],
            "title": clarification["impact_title"],
            "message": clarification["impact"],
            "clarification": clarification,
        }
    result["clarification"] = clarification
    result["report"]["clarification"] = clarification
    if not clarification["skipped"]:
        result["report"]["sections"].insert(1, {"title": "Уточнение для врача", "status": "Готово"})
        # Keep the physician handoff when the patient switches packages.
        routes = [result["route"], *(package["route"] for package in result["packages"])]
        for route in routes:
            physician_step = route[1] if result["checkup_id"] == "child" else route[0]
            physician_step["detail"] += " " + clarification["route_note"]
    return result


def _recommend_base(answers: dict, *, today: date | None = None) -> dict:
    """Select a published programme and return patient-friendly Russian reasons."""
    _validate_answers(answers)
    if answers.get("urgent"):
        return {
            "status": "urgent",
            "title": "Сначала обратитесь за медицинской помощью",
            "message": "При сильной боли в груди, выраженной одышке или внезапном ухудшении самочувствия не ждите check-up. Обратитесь за срочной медицинской помощью.",
        }
    if answers.get("patient_type") == "child":
        today = today or date.today()
        program = PROGRAMS["child"]
        concerns = list(dict.fromkeys(answers.get("child_concerns", [])))
        reasons = [f"Возраст ребёнка — {age_in_words(answers['age'])}", "Анкету заполнил родитель или законный представитель"]
        reasons.extend(f"Вы отметили {CHILD_CONCERNS[item]}" for item in concerns)
        if answers.get("child_chronic"):
            reasons.append("Вы указали хроническое заболевание ребёнка; план уточнит педиатр")
        return {
            "status": "recommended", "checkup_id": "child", "name": program["name"],
            "audience": program["audience"], "summary": program["summary"],
            "price_tenge": program["price_tenge"], "duration_hours": program["duration_hours"],
            "packages": [{"id": "child", **program, "route": _route("child"), "suitable": True}],
            "includes": program["includes"], "reasons": reasons, "route": _route("child"),
            "report": {
                "created_at": today.isoformat(),
                "profile": {"patient_type": "child", "age": answers["age"], "sex": answers["sex"], "concerns": [CHILD_CONCERNS[item] for item in concerns], "family": [], "chronic": answers.get("child_chronic", False), "notes": answers.get("notes", "").strip()},
                "sections": [
                    {"title": "Анкета родителя", "status": "Готово"},
                    {"title": "Осмотр педиатра", "status": "Ожидается"},
                    {"title": "Заключение врача", "status": "Ожидается"},
                ],
            },
            "reminder_date": add_months(today, 1 if answers["age"] == 0 else 12).isoformat(),
            "note": "Это пример детской программы. Состав, цена и сроки осмотров подтверждаются педиатром и клиникой. Ежегодный профилактический осмотр ребёнка можно пройти по месту прикрепления.",
        }
    if answers["sex"] == "female" and answers.get("pregnancy"):
        return {
            "status": "consultation",
            "title": "Программу нужно согласовать с врачом",
            "message": "Во время беременности обследования подбирают индивидуально. Свяжитесь с клиникой перед записью.",
        }

    concerns = list(dict.fromkeys(answers.get("concerns", [])))
    family = list(dict.fromkeys(answers.get("family", [])))
    heart_focus = "heart" in concerns or "pressure" in concerns or ("heart" in family and answers.get("smoking"))
    program_id = "heart" if heart_focus else f"{answers['sex']}_{'extended_40' if answers['age'] >= 40 else 'basic'}"
    program = PROGRAMS[program_id]
    reasons = [f"Ваш возраст — {age_in_words(answers['age'])}", "Вы указали мужской пол" if answers["sex"] == "male" else "Вы указали женский пол"]
    if heart_focus:
        reasons.append("Особое внимание стоит уделить сердцу и сосудам")
    reasons.extend(f"Вы отметили {CONCERNS[item]}" for item in concerns)
    reasons.extend(f"В семейной истории указаны {FAMILY_HISTORY[item]}" for item in family)
    if answers.get("smoking"):
        reasons.append("Вы указали курение")
    if answers.get("low_activity"):
        reasons.append("Вы указали низкую физическую активность")
    if answers.get("chronic"):
        reasons.append("Вы указали хроническое заболевание; программу нужно обсудить с врачом")
    if answers.get("last_checkup"):
        reasons.append("Последний check-up был " + date.fromisoformat(answers["last_checkup"]).strftime("%d.%m.%Y"))

    today = today or date.today()
    return {
        "status": "recommended",
        "checkup_id": program_id,
        "name": program["name"],
        "audience": program["audience"],
        "summary": program["summary"],
        "price_tenge": program["price_tenge"],
        "duration_hours": program["duration_hours"],
        "packages": [{"id": key, **item, "route": _route(key), "suitable": key == "heart" or (('extended_40' in key) == (answers['age'] >= 40))} for key, item in PROGRAMS.items() if key == "heart" or key.startswith(answers["sex"] + "_")],
        "includes": program["includes"],
        "reasons": reasons,
        "route": _route(program_id),
        "report": {
            "created_at": today.isoformat(),
            "profile": {"patient_type": "adult", "age": answers["age"], "sex": answers["sex"], "concerns": [CONCERNS[item] for item in concerns], "family": [FAMILY_HISTORY[item] for item in family], "notes": answers.get("notes", "").strip()},
            "sections": [
                {"title": "Анкета и подбор", "status": "Готово"},
                {"title": "Анализы и исследования", "status": "Ожидаются"},
                {"title": "Заключение врача", "status": "Ожидается"},
            ],
        },
        "reminder_date": add_months(today, 6).isoformat(),
        "note": "Это предварительный подбор. Цены, состав программы и доступность времени демонстрационные; их подтвердит клиника. Сервис не ставит диагноз.",
    }
