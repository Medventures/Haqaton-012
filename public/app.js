const state = { profiles: [], profile: null, programs: [], recommendation: null, selectedProgram: null, slots: [], selectedSlot: null, booking: null };
const el = selector => document.querySelector(selector);

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
}

function formatPrice(value) { return new Intl.NumberFormat('ru-RU').format(value) + ' ₸'; }
function formatDate(value, withTime = false) {
  if (!value) return '—';
  const date = new Date(value.length === 10 ? `${value}T12:00:00` : value);
  return new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', year: 'numeric', ...(withTime ? { hour: '2-digit', minute: '2-digit' } : {}) }).format(date);
}
function programById(id) { return state.programs.find(item => item.id === id); }
async function api(path, options = {}) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Не удалось загрузить данные. Попробуйте ещё раз.');
  return data;
}
async function post(path, body) { return api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }); }
function showError(selector, message) { const target = el(selector); target.textContent = message; target.hidden = false; }

async function loadProfile(id) {
  try {
    const data = await api(`/api/demo-profiles/${encodeURIComponent(id)}`);
    state.profile = data.profile;
    state.recommendation = null;
    state.selectedProgram = null;
    state.selectedSlot = null;
    state.slots = [];
    el('#recommendation').hidden = true;
    el('#booking').hidden = true;
    el('#profile-error').hidden = true;
    el('#recommend-button').disabled = false;
    renderProfileChoices();
    renderProfile();
    const bookingData = await api(`/api/bookings?profile_id=${encodeURIComponent(id)}`);
    state.booking = bookingData.booking;
    renderFollowUp();
    renderDemoOperations();
  } catch (error) { showError('#profile-error', error.message); }
}

function renderProfileChoices() {
  el('#profile-choices').innerHTML = state.profiles.map(profile => `<button class="profile-choice ${state.profile?.id === profile.id ? 'active' : ''}" type="button" data-profile="${escapeHtml(profile.id)}"><span class="choice-person">${escapeHtml(profile.display_name.charAt(0))}</span><span>${escapeHtml(profile.display_name)}</span><span class="choice-arrow">↗</span></button>`).join('');
}

function renderProfile() {
  const p = state.profile;
  if (!p) return;
  el('#profile-name').textContent = p.display_name;
  const values = (items, empty) => items.length ? items.map(escapeHtml).join(' · ') : empty;
  el('#profile-details').innerHTML = `<div class="record-meta"><span>Последний чекап</span><strong>${escapeHtml(formatDate(p.last_checkup))}</strong></div><div class="record-section"><span>Известные заболевания</span><p>${values(p.conditions, 'В карте не указаны')}</p></div><div class="record-section"><span>Лекарства</span><p>${values(p.medications, 'В карте не указаны')}</p></div><div class="record-section"><span>Аллергии</span><p>${values(p.allergies, 'В карте не указаны')}</p></div><div class="record-section"><span>Семейная история</span><p>${values(p.family_history, 'В карте не указана')}</p></div><div class="record-section"><span>Образ жизни</span><p>${values(p.lifestyle, 'В карте не указан')}</p></div><div class="record-section"><span>Последние показатели</span><div class="observation-list">${p.observations.map(item => `<div><strong>${escapeHtml(item.name)}</strong><b>${escapeHtml(item.value)}</b><small>${escapeHtml(formatDate(item.date))}</small></div>`).join('')}</div></div>`;
  el('#health-timeline').innerHTML = `<div class="timeline-list">${[...p.history].reverse().map(item => `<div class="timeline-event"><span class="timeline-dot"></span><small>${escapeHtml(formatDate(item.date))}</small><strong>${escapeHtml(item.title)}</strong><p>${escapeHtml(item.detail)}</p></div>`).join('')}</div>`;
}

function renderFollowUp() {
  const booking = state.booking;
  if (!booking) { el('#follow-up-panel').innerHTML = '<p class="muted">После визита здесь появится дата для обсуждения дальнейшего плана с врачом.</p>'; return; }
  if (booking.status !== 'completed') {
    el('#follow-up-panel').innerHTML = `<div class="follow-date">${escapeHtml(formatDate(booking.visit_at, true))}</div><p>Демонстрационная запись сохранена. После обследования врач предложит срок следующего контакта.</p><span class="status-line">● Ожидает визита</span>`;
    return;
  }
  el('#follow-up-panel').innerHTML = `<div class="follow-date">${escapeHtml(formatDate(booking.follow_up_at))}</div><p>Через шесть месяцев обсудите с врачом, нужен ли повторный чекап. Частоту обследований определяет врач.</p><button id="calendar-reminder" class="button button-secondary" type="button">Добавить напоминание в календарь <span aria-hidden="true">↗</span></button>`;
  el('#calendar-reminder').addEventListener('click', downloadReminder);
}

function downloadReminder() {
  if (!state.booking?.follow_up_at) return;
  const compact = state.booking.follow_up_at.replaceAll('-', '');
  const nextDay = new Date(`${state.booking.follow_up_at}T12:00:00`);
  nextDay.setDate(nextDay.getDate() + 1);
  const end = [nextDay.getFullYear(), String(nextDay.getMonth() + 1).padStart(2, '0'), String(nextDay.getDate()).padStart(2, '0')].join('');
  const contents = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Prime Demo//RU', 'BEGIN:VEVENT', `UID:prime-demo-${state.booking.id}@localhost`, `DTSTART;VALUE=DATE:${compact}`, `DTEND;VALUE=DATE:${end}`, 'SUMMARY:Обсудить с врачом повторный чекап', 'DESCRIPTION:Свяжитесь с клиникой ПРАЙМ и согласуйте необходимость обследования.', 'END:VEVENT', 'END:VCALENDAR'].join('\r\n');
  const url = URL.createObjectURL(new Blob([contents], { type: 'text/calendar;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url; link.download = 'напоминание-прайм.ics'; document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function recommend() {
  if (!state.profile) return;
  const button = el('#recommend-button');
  button.disabled = true; button.textContent = 'Изучаем карту здоровья...';
  try {
    const data = await post('/api/recommend', { profile_id: state.profile.id });
    state.recommendation = data;
    if (data.status !== 'recommended') {
      el('#recommendation').hidden = false;
      el('#recommendation-reasons').innerHTML = `<div class="result-alert"><h3>${escapeHtml(data.title)}</h3><p>${escapeHtml(data.message)}</p></div>`;
      el('#packages').innerHTML = '';
      el('#booking').hidden = true;
    } else {
      renderRecommendation();
      await selectProgram(data.checkup_id, false);
    }
    el('#recommendation').scrollIntoView({ behavior: 'smooth', block: 'start' });
    refreshMetrics();
  } catch (error) { showError('#profile-error', error.message); }
  finally { button.disabled = false; button.innerHTML = 'Подобрать чекап по карте <span aria-hidden="true">↗</span>'; }
}

function renderRecommendation() {
  const r = state.recommendation;
  el('#recommendation').hidden = false;
  el('#recommendation-reasons').innerHTML = `<div class="reason-heading"><span class="circle-icon">✦</span><div><h3>Почему выбрана эта программа?</h3><p>Мы использовали историю карты, а не ответы анкеты</p></div></div><ul>${r.reasons.map(reason => `<li><span aria-hidden="true">✓</span>${escapeHtml(reason)}</li>`).join('')}</ul><div class="data-used">Учтены: ${r.data_used.map(escapeHtml).join(' · ')}</div>`;
  const p = state.profile;
  const eligible = program => program.id === 'heart' || (program.id.startsWith(p.sex) && ((p.age >= 40) === program.id.includes('extended_40')));
  const sorted = [...state.programs].sort((a, b) => Number(b.id === r.checkup_id) - Number(a.id === r.checkup_id));
  el('#packages').innerHTML = sorted.map(program => {
    const recommended = program.id === r.checkup_id;
    const suitable = eligible(program);
    return `<article class="package-card ${recommended ? 'featured' : ''} ${!suitable ? 'muted-package' : ''}"><div class="package-top"><span class="package-tag">${recommended ? 'РЕКОМЕНДУЕМ ПО КАРТЕ' : escapeHtml(program.audience).toUpperCase()}</span><span class="package-star" aria-hidden="true">✳</span></div><h3>${escapeHtml(program.name)}</h3><p>${escapeHtml(program.summary)}</p><div class="package-price">${formatPrice(program.price_tenge)}<small>Справочная цена</small></div><ul>${program.features.map(feature => `<li>${escapeHtml(feature)}</li>`).join('')}</ul><div class="package-bottom"><span>Примерно ${escapeHtml(program.duration_hours)}</span>${suitable ? `<button type="button" data-program="${escapeHtml(program.id)}">${recommended ? 'Выбрать время' : 'Выбрать пакет'} <span aria-hidden="true">↗</span></button>` : '<span>Для другой группы пациентов</span>'}</div></article>`;
  }).join('');
}

async function selectProgram(id, scroll = true) {
  const program = programById(id);
  if (!program || !state.profile) return;
  state.selectedProgram = program;
  state.selectedSlot = null;
  el('#selected-program-name').textContent = program.name;
  el('#selected-program-price').textContent = formatPrice(program.price_tenge);
  el('#booking').hidden = false;
  el('#booking-message').textContent = '';
  el('#slots-list').innerHTML = '<p class="muted">Ищем удобное время...</p>';
  el('#book-button').disabled = true;
  document.querySelectorAll('.package-card').forEach(card => card.classList.remove('chosen'));
  const chosenButton = document.querySelector(`[data-program="${id}"]`);
  chosenButton?.closest('.package-card')?.classList.add('chosen');
  try {
    const data = await api(`/api/slots?program_id=${encodeURIComponent(id)}`);
    state.slots = data.slots;
    renderSlots();
  } catch (error) { el('#slots-list').innerHTML = `<p class="inline-error">${escapeHtml(error.message)}</p>`; }
  if (scroll) el('#booking').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderSlots() {
  if (!state.slots.length) { el('#slots-list').innerHTML = '<p class="muted">Свободных окон пока нет. Позвоните в клинику.</p>'; return; }
  state.selectedSlot ||= state.slots[0].start_at;
  el('#slots-list').innerHTML = state.slots.map((slot, index) => `<button class="slot ${state.selectedSlot === slot.start_at ? 'active' : ''}" type="button" data-slot="${escapeHtml(slot.start_at)}"><span><strong>${escapeHtml(formatDate(slot.start_at, true))}</strong><small>${escapeHtml(slot.load_label)}</small></span><span class="wait-indicator">${index === 0 ? 'ЛУЧШЕЕ ВРЕМЯ' : `Ожидание около ${slot.estimated_wait_minutes} мин`}</span></button>`).join('');
  el('#book-button').disabled = Boolean(state.booking && state.booking.status === 'reserved');
  if (el('#book-button').disabled) el('#booking-message').textContent = 'У вас уже есть демонстрационная запись. Она показана в карте здоровья.';
  renderRoute();
}

function renderRoute() {
  if (!state.selectedSlot || !state.selectedProgram) return;
  const start = new Date(state.selectedSlot);
  const time = offset => new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit' }).format(new Date(start.getTime() + offset * 60000));
  el('#route-list').innerHTML = state.selectedProgram.route.map((step, index) => `<li><span class="day-time">${escapeHtml(time(step.offset_minutes))}</span><span class="day-number">${index + 1}</span><div><strong>${escapeHtml(step.title)}</strong><p>${escapeHtml(step.detail)}</p></div></li>`).join('');
}

async function book() {
  if (!state.profile || !state.selectedProgram || !state.selectedSlot) return;
  const button = el('#book-button'); button.disabled = true; button.textContent = 'Сохраняем запись...';
  try {
    const data = await post('/api/bookings', { profile_id: state.profile.id, program_id: state.selectedProgram.id, start_at: state.selectedSlot });
    state.booking = data.booking;
    el('#booking-message').innerHTML = `Демо запись №${data.booking.id} сохранена на ${escapeHtml(formatDate(data.booking.visit_at, true))}. Для настоящей записи позвоните в клинику: <a href="tel:+77470942621">+7 747 094 26 21</a>.`;
    renderFollowUp(); renderDemoOperations(); refreshMetrics();
  } catch (error) { el('#booking-message').textContent = error.message; button.disabled = false; }
  finally { button.innerHTML = 'Сохранить демо запись <span aria-hidden="true">↗</span>'; }
}

async function refreshMetrics() {
  try {
    const m = await api('/api/metrics');
    const cards = [
      ['Продано чекапов', String(m.checkups_sold), 'Оплаченные программы'],
      ['Выручка', formatPrice(m.sales_tenge), 'По справочному прайсу'],
      ['Время визита', `${m.average_visit_minutes} мин`, 'Среднее по завершённым'],
      ['Повторные визиты', String(m.repeat_visits), 'Пациенты с прошлым чекапом'],
      ['Удовлетворённость', `${m.average_satisfaction} / 5`, `${m.feedback_count} оценок`],
      ['Из подбора в запись', `${m.booking_conversion_percent}%`, `${m.bookings} записей из ${m.recommendations} подборов`],
    ];
    el('#metrics').innerHTML = cards.map(([title, value, detail], index) => `<div class="metric-card ${index === 1 ? 'accent' : ''}"><span>${escapeHtml(title)}</span><strong>${escapeHtml(value)}</strong><small>${escapeHtml(detail)}</small></div>`).join('');
  } catch (error) { el('#metrics').innerHTML = `<p class="inline-error">${escapeHtml(error.message)}</p>`; }
}

function renderDemoOperations() {
  const b = state.booking;
  if (!b) { el('#demo-operations').innerHTML = '<span>Демо управление визитом появится после записи.</span>'; return; }
  if (b.status === 'reserved') {
    el('#demo-operations').innerHTML = `<div><strong>Показать влияние визита на показатели</strong><p>Запись №${b.id}: в демо можно завершить визит, чтобы обновить продажи, время прохождения и повторы.</p></div><button id="complete-demo" class="button button-secondary" type="button">Завершить демо визит <span aria-hidden="true">↗</span></button>`;
    el('#complete-demo').addEventListener('click', completeDemo);
    return;
  }
  el('#demo-operations').innerHTML = `<div><strong>Визит №${b.id} завершён</strong><p>Показатели обновлены. Пациент может оценить посещение.</p></div><div class="rating-actions"><span>Оценка визита</span>${[1, 2, 3, 4, 5].map(score => `<button type="button" data-score="${score}" class="${b.satisfaction === score ? 'active' : ''}" aria-label="Оценка ${score} из 5">${score}</button>`).join('')}</div>`;
}

async function completeDemo() {
  try {
    const data = await post('/api/bookings/complete-demo', { profile_id: state.profile.id, booking_id: state.booking.id });
    state.booking = data.booking;
    renderFollowUp(); renderDemoOperations(); refreshMetrics();
  } catch (error) { el('#demo-operations').innerHTML = `<p class="inline-error">${escapeHtml(error.message)}</p>`; }
}

async function saveScore(score) {
  try {
    const data = await post('/api/bookings/feedback', { profile_id: state.profile.id, booking_id: state.booking.id, score });
    state.booking = data.booking;
    renderDemoOperations(); refreshMetrics();
  } catch (error) { el('#demo-operations').innerHTML = `<p class="inline-error">${escapeHtml(error.message)}</p>`; }
}

el('#profile-choices').addEventListener('click', event => { const button = event.target.closest('[data-profile]'); if (button) loadProfile(button.dataset.profile); });
el('#recommend-button').addEventListener('click', recommend);
el('#packages').addEventListener('click', event => { const button = event.target.closest('[data-program]'); if (button) selectProgram(button.dataset.program); });
el('#slots-list').addEventListener('click', event => { const button = event.target.closest('[data-slot]'); if (button) { state.selectedSlot = button.dataset.slot; renderSlots(); } });
el('#book-button').addEventListener('click', book);
el('#refresh-metrics').addEventListener('click', refreshMetrics);
el('#demo-operations').addEventListener('click', event => { const button = event.target.closest('[data-score]'); if (button) saveScore(Number(button.dataset.score)); });

async function initialize() {
  try {
    const [profiles, catalog] = await Promise.all([api('/api/demo-profiles'), api('/api/catalog')]);
    state.profiles = profiles.profiles;
    state.programs = catalog.programs;
    await loadProfile(state.profiles[0].id);
    refreshMetrics();
  } catch (error) { showError('#profile-error', error.message); el('#profile-name').textContent = 'Не удалось открыть карту'; }
}
initialize();
