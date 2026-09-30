(() => {
  'use strict';
  let accessToken = '';
  let catalog = {};
  let requestVersion = 0;
  let pendingRequest = null;
  const $ = selector => document.querySelector(selector);
  const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
  const number = value => value == null ? 'Пока нет данных' : new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 }).format(value);
  const seconds = value => value == null ? '—' : number(value / 1000) + ' с';
  function card(kicker, title, value, description) { return `<article class="metric-card"><span>${escape(kicker)}</span><h2>${escape(title)}</h2><strong>${escape(value)}</strong><p>${escape(description)}</p></article>`; }
  function render(data) {
    $('#metrics-updated').textContent = 'Обновлено: ' + new Intl.DateTimeFormat('ru-RU', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(data.generated_at));
    $('#metrics-cards').innerHTML = card('01 · ПРОДАЖИ', 'Интерес к записи', number(data.sales.booking_intents), 'Сохранения демо записи. Фактическая выручка не подключена.') + card('02 · ВРЕМЯ', 'Работа ассистента', seconds(data.time.assistant.average_ms), `Среднее время обработки. Измерений: ${data.time.assistant.samples}.`) + card('03 · ПОВТОРНЫЕ ВИЗИТЫ', 'Создано напоминаний', number(data.repeat_visits.reminder_intents), 'Намерение вернуться. Подтверждённые визиты не подключены.') + card('04 · УДОВЛЕТВОРЁННОСТЬ', 'Польза для пациента', data.satisfaction.average_rating == null ? '—' : number(data.satisfaction.average_rating) + ' / 5', `Добровольных оценок: ${data.satisfaction.samples}.`);
    const steps = [['Анкета отправлена',data.counts.questionnaire_started],['План получен',data.counts.recommendation_ready],['Демо запись сохранена',data.counts.booking_intent],['Напоминание создано',data.counts.reminder_intent]];
    const maximum = Math.max(...steps.map(item => item[1]),1);
    $('#metrics-funnel').innerHTML = steps.map(([label,count]) => `<div class="funnel-row"><div><span>${escape(label)}</span><strong>${number(count)}</strong></div><progress max="${maximum}" value="${count}" aria-label="${escape(label)}"></progress></div>`).join('');
    $('#metrics-packages').innerHTML = data.packages.length ? `<table><thead><tr><th>Программа</th><th>Планы</th><th>Записи</th></tr></thead><tbody>${data.packages.map(item=>`<tr><td>${escape(catalog[item.package_id] || 'Программа PRIME')}</td><td>${number(item.recommendations)}</td><td>${number(item.booking_intents)}</td></tr>`).join('')}</tbody></table>` : '<p class="metrics-empty">Здесь появятся программы после первых полученных рекомендаций.</p>';
    $('#metrics-content').hidden = false; $('#metrics-login').hidden = true;
  }
  function closeAccess() {
    accessToken = ''; requestVersion += 1;
    if (pendingRequest) pendingRequest.abort();
    pendingRequest = null;
    $('#metrics-content').hidden = true;
    for (const selector of ['#metrics-cards', '#metrics-funnel', '#metrics-packages', '#metrics-updated']) $(selector).replaceChildren();
    $('#metrics-error').hidden = true; $('#metrics-error').textContent = '';
    $('#metrics-refresh').disabled = false;
    $('#admin-token').value = ''; $('#metrics-login').hidden = false; $('#admin-token').focus();
  }
  async function refresh() {
    const version = ++requestVersion;
    if (pendingRequest) pendingRequest.abort();
    const controller = new AbortController();
    pendingRequest = controller;
    $('#metrics-error').hidden = true; $('#metrics-refresh').disabled = true;
    try {
      const response = await fetch('/api/metrics', { headers: { Authorization: 'Bearer ' + accessToken }, signal: controller.signal });
      let data;
      try { data = await response.json(); } catch { throw new Error('Не удалось прочитать ответ сервера. Попробуйте ещё раз.'); }
      if (version !== requestVersion || !accessToken) return;
      if (!response.ok) {
        const message = typeof data.error === 'string' ? data.error : 'Не удалось открыть статистику.';
        if (response.status === 401 || response.status === 403) closeAccess();
        $('#metrics-error').textContent = message; $('#metrics-error').hidden = false;
        return;
      }
      render(data);
    } catch (error) {
      if (controller.signal.aborted || version !== requestVersion) return;
      $('#metrics-error').textContent = error instanceof TypeError ? 'Не удалось загрузить статистику. Проверьте связь и попробуйте ещё раз.' : error.message;
      $('#metrics-error').hidden = false;
    }
    finally { if (version === requestVersion) { pendingRequest = null; $('#metrics-refresh').disabled = false; } }
  }
  $('#metrics-login').addEventListener('submit', async event => {
    event.preventDefault(); accessToken = $('#admin-token').value.trim();
    $('#metrics-login button').disabled = true;
    await refresh(); $('#admin-token').value = ''; $('#metrics-login button').disabled = false;
  });
  $('#metrics-refresh').addEventListener('click', refresh);
  $('#metrics-logout').addEventListener('click', closeAccess);
  fetch('/api/catalog').then(r=>r.json()).then(data=>{catalog=Object.fromEntries(data.programs.map(p=>[p.id,p.name]));}).catch(()=>{});
})();
