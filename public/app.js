const form = document.querySelector('#checkup-form');
const resultSection = document.querySelector('#recommendation');
const bookingSection = document.querySelector('#booking');
const healthSection = document.querySelector('#health-card');
const reminderSection = document.querySelector('#reminder');
const errorBox = document.querySelector('#form-error');
const submitButton = document.querySelector('#submit-button');
const pregnancyRow = document.querySelector('#pregnancy-row');
const REPORT_KEY = 'prime-checkup-report-v7';
const REMINDER_KEY = 'prime-checkup-reminder-v2';
const BOOKING_KEY = 'prime-checkup-booking-v1';
let currentRecommendation = null;
let currentAnswers = null;
let selectedPackage = null;
let selectedDate = null;
let selectedTime = null;
let currentRating = null;

function trackEvent(event, extra = {}) {
  fetch('/api/events', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ event, mode: currentAnswers?.patient_type || form.elements.patient_type.value, ...extra }), keepalive: true }).catch(() => {});
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
}
function formatPrice(value) { return new Intl.NumberFormat('ru-RU').format(value) + ' ₸'; }
function formatDate(value) {
  if (!value) return 'Не указана';
  const date = new Date(`${value}T12:00:00`);
  return new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' }).format(date);
}
function todayLocal() {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}
function checkedValues(selector) { return [...document.querySelectorAll(`${selector} input:checked`)].map(input => input.value); }
function readStored(key) { try { return JSON.parse(sessionStorage.getItem(key) || 'null'); } catch { return null; } }
function store(key, value) { try { sessionStorage.setItem(key, JSON.stringify(value)); } catch { /* Storage may be disabled. */ } }
document.querySelectorAll('input[name="sex"]').forEach(input => input.addEventListener('change', () => {
  const female = form.elements.sex.value === 'female';
  pregnancyRow.hidden = !female;
  if (!female) form.elements.pregnancy.checked = false;
}));
document.querySelectorAll('input[name="patient_type"]').forEach(input => input.addEventListener('change', () => {
  const child = form.elements.patient_type.value === 'child';
  document.querySelector('#adult-fields').hidden = child;
  document.querySelector('#child-fields').hidden = !child;
  document.querySelector('#form-title').textContent = child ? 'Расскажите о здоровье ребёнка' : 'Расскажите немного о себе';
  document.querySelector('.form-intro h2').innerHTML = child ? 'Начнём<br>с ребёнка.' : 'Начнём<br>с вас.';
  document.querySelector('.urgent-row span').textContent = child
    ? 'Сейчас у ребёнка есть сильная боль в груди, выраженная одышка или внезапное ухудшение самочувствия'
    : 'Сейчас есть сильная боль в груди, выраженная одышка или внезапное ухудшение самочувствия';
  errorBox.hidden = true;
}));
document.querySelector('#last-checkup').max = todayLocal();
document.querySelector('#child-last-checkup').max = todayLocal();

form.addEventListener('submit', async event => {
  event.preventDefault();
  if (submitButton.disabled) return;
  errorBox.hidden = true;
  const urgent = form.elements.urgent.checked;
  const child = form.elements.patient_type.value === 'child';
  const ageInput = child ? form.elements.child_age : form.elements.age;
  const age = ageInput.value === '' ? NaN : Number(ageInput.value);
  const sex = child ? form.elements.child_sex.value : form.elements.sex.value;
  if (!urgent && (!Number.isInteger(age) || (child ? age < 0 || age > 17 : age < 18 || age > 100))) {
    errorBox.textContent = child ? 'Укажите возраст ребёнка от 0 до 17 лет.' : 'Укажите возраст от 18 до 100 лет.';
    errorBox.hidden = false;
    ageInput.focus();
    return;
  }
  if (!urgent && !sex) {
    errorBox.textContent = child ? 'Выберите пол ребёнка.' : 'Выберите пол для подбора программы.';
    errorBox.hidden = false;
    return;
  }
  if (child && !urgent && !form.elements.guardian_confirmed.checked) {
    errorBox.textContent = 'Анкету ребёнка должен заполнить родитель или законный представитель.';
    errorBox.hidden = false;
    form.elements.guardian_confirmed.focus();
    return;
  }
  const answers = child ? {
    patient_type: 'child', age, sex,
    guardian_confirmed: form.elements.guardian_confirmed.checked,
    child_concerns: checkedValues('#child-concerns'),
    child_chronic: form.elements.child_chronic.checked,
    urgent,
    last_checkup: form.elements.child_last_checkup.value || null,
    preferred_time: form.elements.child_preferred_time.value,
    notes: form.elements.child_notes.value.trim(),
  } : {
    patient_type: 'adult', age, sex,
    concerns: checkedValues('#concerns'),
    family: checkedValues('#family'),
    smoking: form.elements.smoking.checked,
    low_activity: form.elements.low_activity.checked,
    chronic: form.elements.chronic.checked,
    pregnancy: sex === 'female' && form.elements.pregnancy.checked,
    urgent,
    last_checkup: form.elements.last_checkup.value || null,
    preferred_time: form.elements.preferred_time.value,
    notes: form.elements.notes.value.trim(),
  };
  answers.ai_consent = form.elements.ai_consent.checked;
  const flowStarted = performance.now();
  trackEvent('questionnaire_started', { mode: answers.patient_type });
  submitButton.disabled = true;
  submitButton.textContent = 'Находим важное уточнение...';
  let returnedToForm = false;
  try {
    let processingStarted = performance.now();
    const question = await PrimeAssistant.run('/api/agent/clarify', answers);
    let processingMs = performance.now() - processingStarted;
    if (question === null) { returnedToForm = true; return; }
    if (question.status === 'question') {
      const clarification = await PrimeAssistant.ask(question);
      if (clarification === null) { returnedToForm = true; return; }
      answers.clarification = clarification;
    }
    submitButton.textContent = 'Собираем ваш план...';
    processingStarted = performance.now();
    const data = ['urgent', 'consultation'].includes(question.status) ? question : await PrimeAssistant.run('/api/agent/recommend', answers);
    processingMs += performance.now() - processingStarted;
    if (data === null) { returnedToForm = true; return; }
    trackEvent('assistant_completed', { mode: answers.patient_type, duration_ms: Math.min(3600000, Math.round(processingMs)) });
    currentRating = null;
    if (data.status === 'recommended') {
      try { sessionStorage.removeItem(BOOKING_KEY); } catch { /* Storage may be disabled. */ }
      store(REPORT_KEY, { recommendation: data, answers });
      trackEvent('recommendation_ready', { mode: answers.patient_type, package_id: data.checkup_id, duration_ms: Math.min(3600000, Math.round(performance.now() - flowStarted)) });
    }
    else { try { sessionStorage.removeItem(REPORT_KEY); } catch { /* Storage may be disabled. */ } }
    render(data, answers);
    const resultHeading = resultSection.querySelector('h2');
    resultHeading.tabIndex = -1;
    resultHeading.focus({ preventScroll: true });
    resultSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (error) {
    errorBox.textContent = error.message || 'Не удалось получить рекомендацию. Попробуйте ещё раз.';
    errorBox.hidden = false;
  } finally {
    submitButton.disabled = false;
    submitButton.innerHTML = 'Получить рекомендацию <span aria-hidden="true">↗</span>';
    if (returnedToForm) submitButton.focus({ preventScroll: true });
  }
});

function render(data, answers) {
  resultSection.hidden = false;
  if (data.status !== 'recommended') {
    currentRecommendation = null;
    currentAnswers = null;
    selectedPackage = null;
    selectedDate = null;
    selectedTime = null;
    bookingSection.hidden = true;
    healthSection.hidden = true;
    reminderSection.hidden = true;
    bookingSection.replaceChildren();
    healthSection.replaceChildren();
    reminderSection.replaceChildren();
    try { sessionStorage.removeItem(BOOKING_KEY); } catch { /* Storage may be disabled. */ }
    resultSection.innerHTML = `<div class="important-result"><span class="section-kicker">ВАЖНО</span><h2>${escapeHtml(data.title)}</h2><p>${escapeHtml(data.message)}</p><a class="button button-secondary" href="#questionnaire">Изменить ответы <span aria-hidden="true">↗</span></a></div>`;
    if (data.clarification) resultSection.insertAdjacentHTML('beforeend', PrimeAssistant.receipt(data.clarification));
    return;
  }
  currentRecommendation = data;
  currentAnswers = answers;
  selectedPackage = data.packages.find(item => item.id === data.checkup_id);
  const reasons = data.reasons.map(reason => `<li><span aria-hidden="true">✓</span>${escapeHtml(reason)}</li>`).join('');
  const includes = data.includes.map(item => `<li>${escapeHtml(item)}</li>`).join('');
  const route = data.route.map((step, index) => `<li><span class="route-time">${escapeHtml(step.time)}</span><span class="route-number">${index + 1}</span><div><strong>${escapeHtml(step.title)}</strong><p>${escapeHtml(step.detail)}</p></div></li>`).join('');
  const alternatives = data.packages.filter(item => item.id !== data.checkup_id).sort((a, b) => Number(b.suitable) - Number(a.suitable)).map(item => `<article class="alternative-card ${item.suitable ? '' : 'alternative-disabled'}"><span class="package-tag">${escapeHtml(item.audience)}</span><h3>${escapeHtml(item.name)}</h3><p>${escapeHtml(item.summary)}</p><strong>${formatPrice(item.price_tenge)}</strong><small>Демо-цена · примерно ${escapeHtml(item.duration_hours)}</small>${item.suitable ? `<button class="button button-secondary" type="button" data-package="${escapeHtml(item.id)}">Выбрать пакет ↗</button>` : '<span class="package-unavailable">Для другой возрастной группы</span>'}</article>`).join('');
  resultSection.innerHTML = `<div class="section-heading"><div><span class="section-kicker">ШАГ 02 · ПОДБОР ПАКЕТА</span><h2>Рекомендуемый check-up</h2><p>Программа подобрана по вашим ответам</p></div><button id="print-plan" class="text-button" type="button">Распечатать план ↗</button></div>
    <div class="result-grid"><article class="program-card"><div class="program-card-top"><span>РЕКОМЕНДУЕМ ВАМ</span><span aria-hidden="true">✳</span></div><p class="audience">${escapeHtml(data.audience)}</p><h3>${escapeHtml(data.name)}</h3><p class="program-summary">${escapeHtml(data.summary)}</p><div class="program-price">${formatPrice(data.price_tenge)}<small>Демо-цена · примерно ${escapeHtml(data.duration_hours)}</small></div><h4>Что входит в программу</h4><ul>${includes}</ul><button class="button button-primary package-action" type="button" data-package="${escapeHtml(data.checkup_id)}">Выбрать день и время ↗</button></article>
    <div class="result-side"><article class="reason-card"><div class="card-title"><span class="card-icon">✦</span><h3>Почему мы рекомендуем этот check-up?</h3></div><ul class="reason-list">${reasons}</ul></article><article class="route-card"><div class="card-title"><span class="card-icon lavender">↗</span><div><h3>Маршрут на один день</h3><p>Примерный порядок посещений</p></div></div><ol class="route-list">${route}</ol></article></div></div>
    <div class="package-options"><div><span class="section-kicker">ЕСТЬ ВЫБОР</span><h3>Другие пакеты PRIME</h3><p>Можно выбрать другой пакет. Состав обследования подтвердит врач.</p></div><div class="alternative-grid">${alternatives}</div></div><p class="result-note">${escapeHtml(data.note)}</p>`;
  document.querySelector('#print-plan').addEventListener('click', () => window.print());
  resultSection.querySelector('.section-heading').insertAdjacentHTML('afterend', PrimeAssistant.receipt(data.clarification));
  if (!alternatives) resultSection.querySelector('.package-options').hidden = true;
  resultSection.querySelectorAll('[data-package]').forEach(button => button.addEventListener('click', () => selectPackage(button.dataset.package)));
  renderBooking();
  renderHealthCard(data, answers);
  renderReminder(data);
}

function demoSlots() {
  const slots = [];
  const times = ['08:30', '09:00', '09:30', '10:00'];
  const start = new Date(`${todayLocal()}T12:00:00`);
  for (let offset = 1; slots.length < 28 && offset < 20; offset++) {
    const day = new Date(start);
    day.setDate(day.getDate() + offset);
    if (day.getDay() === 0 || day.getDay() === 6) continue;
    const date = `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, '0')}-${String(day.getDate()).padStart(2, '0')}`;
    times.forEach((time, index) => slots.push({ date, time, wait: 5 + ((offset * 3 + index * 2) % 4) * 5 }));
  }
  return slots;
}

function selectPackage(id) {
  selectedPackage = currentRecommendation?.packages.find(item => item.id === id);
  if (!selectedPackage) return;
  selectedDate = null;
  selectedTime = null;
  renderBooking();
  bookingSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderBooking() {
  if (!selectedPackage || !currentAnswers) return;
  bookingSection.hidden = false;
  const slots = demoSlots();
  const preferred = currentAnswers.preferred_time || 'any';
  const suitable = slots.filter(slot => preferred === 'any' || (preferred === 'morning' ? slot.time <= '09:00' : slot.time >= '09:30'));
  const best = [...suitable].sort((a, b) => a.wait - b.wait || a.date.localeCompare(b.date) || a.time.localeCompare(b.time))[0];
  if (!selectedDate || !slots.some(slot => slot.date === selectedDate)) selectedDate = best.date;
  if (!selectedTime || !slots.some(slot => slot.date === selectedDate && slot.time === selectedTime)) selectedTime = selectedDate === best.date ? best.time : '08:30';
  const days = [...new Set(slots.map(slot => slot.date))];
  const dayButtons = days.map(date => `<button type="button" class="calendar-day ${date === selectedDate ? 'active' : ''} ${date === best.date ? 'best' : ''}" data-date="${date}"><span>${escapeHtml(new Intl.DateTimeFormat('ru-RU', { weekday: 'short' }).format(new Date(`${date}T12:00:00`)))}</span><strong>${escapeHtml(new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short' }).format(new Date(`${date}T12:00:00`)))}</strong>${date === best.date ? '<small>Спокойнее</small>' : ''}</button>`).join('');
  const timeButtons = slots.filter(slot => slot.date === selectedDate).map(slot => `<button type="button" class="calendar-time ${slot.time === selectedTime ? 'active' : ''}" data-time="${slot.time}"><strong>${slot.time}</strong><span>Ожидание ≈ ${slot.wait} мин</span></button>`).join('');
  const chosen = slots.find(slot => slot.date === selectedDate && slot.time === selectedTime);
  const saved = readStored(BOOKING_KEY);
  const status = saved?.checkup_id === selectedPackage.id ? `Сохранена демо запись: ${formatDate(saved.date)}, ${saved.time}.` : 'Выберите день и время, затем сохраните демо запись.';
  bookingSection.innerHTML = `<div class="section-heading"><div><span class="section-kicker">ШАГ 03 · КАЛЕНДАРЬ</span><h2>Выберите удобный день</h2><p>Для пакета «${escapeHtml(selectedPackage.name)}» · ${formatPrice(selectedPackage.price_tenge)}</p></div></div><div class="booking-grid"><div class="calendar-card"><div class="calendar-intro"><span class="card-icon">◷</span><div><h3>Демо-календарь клиники</h3><p>Показана примерная загрузка, чтобы выбрать спокойное время.</p></div></div><p class="calendar-caption">Доступные дни</p><div class="calendar-days">${dayButtons}</div><p class="calendar-caption">Начало обследования · ${escapeHtml(formatDate(selectedDate))}</p><div class="calendar-times">${timeButtons}</div></div><div class="booking-summary"><span class="section-kicker">ВАШ ВЫБОР</span><h3>${escapeHtml(selectedPackage.name)}</h3><strong>${escapeHtml(formatDate(selectedDate))}<br>в ${escapeHtml(selectedTime)}</strong><p>Примерное ожидание — ${chosen.wait} мин. Демо-цена пакета — ${formatPrice(selectedPackage.price_tenge)}.</p><div class="quiet-tip">✦ Самое спокойное окно с учётом вашего ответа: ${escapeHtml(formatDate(best.date))} в ${best.time}, ожидание около ${best.wait} мин.</div><button id="book-demo" class="button button-primary" type="button">Сохранить демо запись ↗</button><p id="booking-status" class="booking-status" role="status">${escapeHtml(status)}</p></div></div><p class="result-note">Дни, время и оценка очереди показаны для демонстрации. Настоящую запись и стоимость подтверждает клиника.</p>`;
  bookingSection.querySelectorAll('[data-date]').forEach(button => button.addEventListener('click', () => { selectedDate = button.dataset.date; selectedTime = null; renderBooking(); }));
  bookingSection.querySelectorAll('[data-time]').forEach(button => button.addEventListener('click', () => { selectedTime = button.dataset.time; renderBooking(); }));
  bookingSection.querySelector('#book-demo').addEventListener('click', saveDemoBooking);
}

function saveDemoBooking() {
  if (!selectedPackage || !selectedDate || !selectedTime) return;
  const previousBooking = readStored(BOOKING_KEY);
  if (previousBooking?.checkup_id !== selectedPackage.id || previousBooking?.date !== selectedDate || previousBooking?.time !== selectedTime) trackEvent('booking_intent', { package_id: selectedPackage.id });
  store(BOOKING_KEY, { checkup_id: selectedPackage.id, date: selectedDate, time: selectedTime });
  const compact = selectedDate.replaceAll('-', '');
  const start = selectedTime.replace(':', '') + '00';
  const endHour = String(Number(selectedTime.slice(0, 2)) + (selectedPackage.id === 'child' ? 3 : 6)).padStart(2, '0');
  const end = `${endHour}${selectedTime.slice(3)}00`;
  const calendar = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Prime Checkup Demo//RU', 'BEGIN:VEVENT', `UID:prime-visit-${compact}-${start}@localhost`, `DTSTART:${compact}T${start}`, `DTEND:${compact}T${end}`, `SUMMARY:Демо запись на check-up PRIME`, `DESCRIPTION:${selectedPackage.name}. Это демонстрация. Подтвердите запись и цену в клинике.`, 'END:VEVENT', 'END:VCALENDAR'].join('\r\n');
  const url = URL.createObjectURL(new Blob([calendar], { type: 'text/calendar;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url; link.download = 'демо-запись-prime.ics'; document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  document.querySelector('#booking-status').textContent = `Демо запись сохранена на ${formatDate(selectedDate)} в ${selectedTime}. Файл для календаря скачан. Подтвердите запись в клинике.`;
  if (currentRecommendation && currentAnswers) renderHealthCard(currentRecommendation, currentAnswers);
}

function renderHealthCard(data, answers) {
  healthSection.hidden = false;
  const report = data.report;
  const child = report.profile.patient_type === 'child';
  const age = report.profile.age;
  const ageEnding = age % 100 >= 11 && age % 100 <= 14 ? 'лет' : ({ 1: 'год', 2: 'года', 3: 'года', 4: 'года' }[age % 10] || 'лет');
  const details = child ? [
    ['Анкету заполнил', 'Родитель или законный представитель'],
    ['Возраст ребёнка', `${age} ${ageEnding}`],
    ['Пол ребёнка', report.profile.sex === 'female' ? 'Девочка' : 'Мальчик'],
    ['Вопросы о здоровье', report.profile.concerns.join(', ') || 'Не указаны'],
    ['Хроническое заболевание', report.profile.chronic ? 'Указано родителем' : 'Не указано'],
    ['Последний осмотр', answers.last_checkup ? formatDate(answers.last_checkup) : 'Не указан'],
    ['Сообщение педиатру', report.profile.notes || 'Не указано'],
  ] : [
    ['Возраст', `${age} ${ageEnding}`],
    ['Пол', report.profile.sex === 'female' ? 'Женский' : 'Мужской'],
    ['Жалобы', report.profile.concerns.join(', ') || 'Не указаны'],
    ['Семейная история', report.profile.family.join(', ') || 'Не указана'],
    ['Последний check-up', answers.last_checkup ? formatDate(answers.last_checkup) : 'Не указан'],
    ['Сообщение врачу', report.profile.notes || 'Не указано'],
  ];
  const booking = readStored(BOOKING_KEY);
  if (booking?.date && booking?.checkup_id) details.push(['Демо запись', `${formatDate(booking.date)} в ${booking.time}`]);
  healthSection.innerHTML = `<div class="section-heading"><div><span class="section-kicker">ШАГ 04 · КАРТА ЗДОРОВЬЯ</span><h2>${child ? 'Демо-отчёт ребёнка' : 'Ваш демо-отчёт'}</h2><p>Все этапы check-up в одном месте</p></div><span class="report-date">Создан ${escapeHtml(formatDate(report.created_at))}</span></div><div class="report-grid"><article class="report-card"><div class="report-card-title"><span class="card-icon">▤</span><div><h3>${child ? 'Данные ребёнка' : 'Ваши данные'}</h3><p>Информация из анкеты</p></div></div>${details.map(([label, value]) => `<div class="report-row"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join('')}</article><article class="report-card"><div class="report-card-title"><span class="card-icon lavender">◷</span><div><h3>Ход обследования</h3><p>${escapeHtml(data.name)}</p></div></div>${report.sections.map((item, index) => `<div class="report-status"><span class="status-dot ${item.status === 'Готово' ? 'done' : ''}"></span><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.status)}</small></div>`).join('')}<p class="report-hint">После реального check-up результаты и заключение добавляет клиника. Здесь показан образец отчёта.</p></article></div>`;
  healthSection.insertAdjacentHTML('beforeend', PrimeAssistant.receipt(data.clarification, true));
  healthSection.insertAdjacentHTML('beforeend', `<div class="satisfaction-card"><div><span class="section-kicker">ВАШЕ ВПЕЧАТЛЕНИЕ</span><h3>Стало понятнее, с чего начать?</h3><p>Оцените пользу подбора от 1 до 5.</p></div><div class="rating-controls" role="group" aria-label="Оценка подбора">${[1,2,3,4,5].map(rating => `<button type="button" data-rating="${rating}" aria-label="Оценка ${rating} из 5" ${currentRating ? 'disabled' : ''} class="${currentRating === rating ? 'selected' : ''}">${rating}</button>`).join('')}<span role="status">${currentRating ? 'Спасибо за вашу оценку!' : '1 — не помогло · 5 — всё понятно'}</span></div></div><div class="report-privacy"><p>Отчёт хранится в этой вкладке до её закрытия. Для сохранения используйте «Распечатать план».</p><button type="button" id="clear-health-data">Удалить мои ответы</button></div>`);
  healthSection.querySelectorAll('[data-rating]').forEach(button => button.addEventListener('click', () => {
    if (currentRating) return;
    currentRating = Number(button.dataset.rating);
    trackEvent('satisfaction_submitted', { package_id: data.checkup_id, rating: currentRating });
    healthSection.querySelectorAll('[data-rating]').forEach(item => { item.disabled = true; item.classList.toggle('selected', item === button); });
    healthSection.querySelector('.rating-controls [role="status"]').textContent = 'Спасибо за вашу оценку!';
  }));
  document.querySelector('#clear-health-data').addEventListener('click', clearHealthData);
}

function clearHealthData() {
  for (const storageName of ['sessionStorage', 'localStorage']) {
    try {
      const storage = window[storageName];
      for (const key of Object.keys(storage)) if (key.startsWith('prime-checkup-')) storage.removeItem(key);
    } catch { /* Storage may be disabled. */ }
  }
  currentRecommendation = currentAnswers = selectedPackage = selectedDate = selectedTime = currentRating = null;
  [resultSection, bookingSection, healthSection, reminderSection].forEach(section => { section.hidden = true; section.replaceChildren(); });
  form.reset();
  form.elements.patient_type[0].dispatchEvent(new Event('change', { bubbles: true }));
  errorBox.hidden = true;
  document.querySelector('#age').focus();
  form.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderReminder(data) {
  reminderSection.hidden = false;
  const saved = readStored(REMINDER_KEY);
  const date = saved?.checkup_id === data.checkup_id ? saved.date : data.reminder_date;
  const child = data.checkup_id === 'child';
  const reminderCopy = child
    ? (data.report.profile.age === 0 ? 'На первом году жизни сроки профилактических осмотров уточните у педиатра. Дату напоминания можно изменить.' : 'Дети проходят профилактический осмотр ежегодно. Дату следующего осмотра уточните у педиатра.')
    : 'Через шесть месяцев можно обсудить с врачом необходимость повторного обследования. Частоту профилактических осмотров определяет врач.';
  reminderSection.innerHTML = `<div class="reminder-copy"><span class="section-kicker">ШАГ 05 · НАПОМИНАНИЕ</span><h2>${child ? 'Напомнить об осмотре ребёнка' : 'Вернуться к своему здоровью вовремя'}</h2><p>${escapeHtml(reminderCopy)}</p><div class="reminder-controls"><label for="reminder-date">Дата напоминания</label><input id="reminder-date" type="date" min="${todayLocal()}" value="${escapeHtml(date)}"><button id="save-reminder" class="button button-primary" type="button">Добавить в календарь <span aria-hidden="true">↗</span></button></div><p id="reminder-status" class="reminder-status" role="status">${saved?.checkup_id === data.checkup_id ? `Напоминание сохранено на ${escapeHtml(formatDate(saved.date))}.` : 'Напоминание сохраняется в этом браузере; файл можно добавить в календарь.'}</p></div><div class="reminder-art" aria-hidden="true"><span>✳</span><strong>${escapeHtml(formatDate(date))}</strong><small>Следующий контакт с врачом</small></div>`;
  document.querySelector('#save-reminder').addEventListener('click', () => saveReminder(data));
}

function saveReminder(data) {
  const input = document.querySelector('#reminder-date');
  const selected = input.value;
  if (!selected || selected < todayLocal()) {
    document.querySelector('#reminder-status').textContent = 'Выберите сегодняшнюю или будущую дату.';
    return;
  }
  const previousReminder = readStored(REMINDER_KEY);
  if (previousReminder?.date !== selected || previousReminder?.checkup_id !== data.checkup_id) trackEvent('reminder_intent', { package_id: data.checkup_id });
  store(REMINDER_KEY, { date: selected, checkup_id: data.checkup_id });
  const next = new Date(`${selected}T12:00:00`);
  next.setDate(next.getDate() + 1);
  const compact = value => value.replaceAll('-', '');
  const end = `${next.getFullYear()}${String(next.getMonth() + 1).padStart(2, '0')}${String(next.getDate()).padStart(2, '0')}`;
  const calendar = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Prime Checkup Demo//RU', 'BEGIN:VEVENT', `UID:prime-checkup-${compact(selected)}@localhost`, `DTSTART;VALUE=DATE:${compact(selected)}`, `DTEND;VALUE=DATE:${end}`, data.checkup_id === 'child' ? 'SUMMARY:Обсудить осмотр ребёнка с педиатром' : 'SUMMARY:Обсудить повторный check-up с врачом', 'DESCRIPTION:Свяжитесь с PRIME и согласуйте необходимость обследования.', 'END:VEVENT', 'END:VCALENDAR'].join('\r\n');
  const url = URL.createObjectURL(new Blob([calendar], { type: 'text/calendar;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url; link.download = 'напоминание-prime.ics'; document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  document.querySelector('#reminder-status').textContent = `Напоминание сохранено на ${formatDate(selected)}. Откройте скачанный файл в календаре.`;
  document.querySelector('.reminder-art strong').textContent = formatDate(selected);
}

const savedReport = readStored(REPORT_KEY);
if (savedReport?.recommendation?.status === 'recommended' && savedReport.answers) render(savedReport.recommendation, savedReport.answers);

fetch('/api/config').then(response => response.ok ? response.json() : Promise.reject()).then(config => {
  document.querySelector('#ai-availability').textContent = config.ai_available ? '✦ ИИ-ассистент готов к работе' : 'Сейчас доступен подбор по правилам';
}).catch(() => { document.querySelector('#ai-availability').textContent = 'Доступность ИИ проверим при отправке анкеты'; });

document.querySelectorAll('[data-example]').forEach(button => button.addEventListener('click', () => {
  form.reset();
  const child = button.dataset.example === 'child';
  form.elements.patient_type.value = child ? 'child' : 'adult';
  form.elements.patient_type[child ? 1 : 0].dispatchEvent(new Event('change', { bubbles: true }));
  pregnancyRow.hidden = true;
  if (child) {
    form.elements.child_age.value = 8;
    form.elements.child_sex.value = 'female';
    document.querySelector('#child-concerns input[value="vision"]').checked = true;
    form.elements.child_notes.value = 'Дочь во время чтения быстро устаёт и подносит книгу близко. В школе стала медленнее переписывать с доски.';
    form.elements.child_notes.focus();
  } else {
    form.elements.age.value = 32;
    form.elements.sex.value = 'male';
    document.querySelector('#concerns input[value="fatigue"]').checked = true;
    if (button.dataset.example === 'shifts') {
      document.querySelector('#concerns input[value="pressure"]').checked = true;
      form.elements.notes.value = 'Работаю ночными сменами. После смен чувствую усталость и тяжесть в голове. В выходные становится лучше, но не всегда.';
    } else {
      form.elements.notes.value = 'Две недели назад сдавал общий анализ крови и проверял щитовидную железу. Результаты есть, с врачом пока не обсуждал. Усталость осталась.';
    }
    form.elements.notes.focus();
  }
  errorBox.hidden = true;
  document.querySelector('#questionnaire').scrollIntoView({ behavior: 'smooth', block: 'start' });
}));
