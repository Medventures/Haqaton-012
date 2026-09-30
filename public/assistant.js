(() => {
  'use strict';
  const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
  const mark = '<span class="assistant-mark" aria-hidden="true">✳</span>';
  const orbit = '<div class="assistant-orbit" aria-hidden="true"><span class="orbit-ring ring-one"></span><span class="orbit-ring ring-two"></span><span class="orbit-ring ring-three"></span><span class="orbit-core">✳</span><i class="orbit-dot dot-one"></i><i class="orbit-dot dot-two"></i></div>';
  const modes = { live: 'Живой ИИ-анализ', rules: 'Подбор по правилам', fallback: 'Резервный подбор' };
  function openDialog(content, label) {
    const dialog = document.createElement('dialog');
    dialog.className = 'assistant-dialog';
    dialog.setAttribute('aria-labelledby', label);
    dialog.innerHTML = content;
    document.body.append(dialog);
    document.body.classList.add('assistant-open');
    dialog.showModal();
    dialog.querySelector(`#${label}`)?.focus({ preventScroll: true });
    return dialog;
  }
  function closeDialog(dialog) {
    dialog.close(); dialog.remove();
    document.body.classList.remove('assistant-open');
  }
  function rail(signals = [], processing = false) {
    return `<aside class="assistant-rail ${processing ? 'rail-processing' : ''}"><div class="assistant-brand">${mark}<span>PRIME<small>ВАШ АССИСТЕНТ</small></span></div>${orbit}<div class="assistant-rail-copy"><span class="assistant-eyebrow">ВНИМАНИЕ К ДЕТАЛЯМ</span><h2>За ответами —<br>ваша история.</h2><p>Одна деталь поможет подготовить более точный разговор с врачом.</p></div><div class="assistant-evidence"><span>ОПОРА НА ВАШИ ОТВЕТЫ</span>${signals.map((signal, index) => `<div class="evidence-item"><i aria-hidden="true">${String(index + 1).padStart(2, '0')}</i><div><small>${escape(signal.label)}</small><strong>${escape(signal.value)}</strong></div></div>`).join('')}</div><p class="assistant-rail-note">${mark} В центре внимания — ваш вопрос о здоровье.</p></aside>`;
  }

  async function run(path, answers) {
    const controller = new AbortController();
    let cancelled = false;
    const isPlan = path.endsWith('/recommend');
    const title = isPlan ? 'Собираем историю в понятный план.' : 'Ищем деталь, которую важно уточнить.';
    const dialog = openDialog(`<div class="assistant-layout">${rail([], true)}<div class="assistant-conversation processing-panel"><header class="assistant-topline"><span><i aria-hidden="true"></i> ${answers.ai_consent ? 'АССИСТЕНТ РАБОТАЕТ С АНКЕТОЙ' : 'ПОДГОТОВКА ПО ВАШИМ ОТВЕТАМ'}</span><button class="assistant-close" type="button" aria-label="Отменить и вернуться к анкете">×</button></header><span class="processing-label">${isPlan ? 'ОТ ОТВЕТА К ДЕЙСТВИЮ' : 'КАЖДАЯ ДЕТАЛЬ ИМЕЕТ ЗНАЧЕНИЕ'}</span><h2 id="processing-title" tabindex="-1">${title}</h2><p class="processing-intro">${isPlan ? 'Покажем, что именно изменилось после вашего уточнения.' : 'Сопоставляем ваши ответы и готовим один вопрос, который поможет врачу лучше понять ситуацию.'}</p><ol class="agent-stages" aria-label="Этапы обработки"></ol><p class="processing-status" role="status" aria-live="polite">Соединяемся с сервисом…</p><div class="processing-foot"><span>✦</span><p>Программа и стоимость берутся из каталога клиники. Решение об обследованиях остаётся за врачом.</p></div><button class="assistant-skip processing-cancel" type="button">Вернуться к анкете</button></div></div>`, 'processing-title');
    const cancel = () => { cancelled = true; controller.abort(); };
    dialog.querySelector('.assistant-close').addEventListener('click', cancel);
    dialog.querySelector('.processing-cancel').addEventListener('click', cancel);
    dialog.addEventListener('cancel', event => { event.preventDefault(); cancel(); });
    const stages = new Map();
    let result;
    const timeout = setTimeout(() => controller.abort(), 180000);
    const consume = event => {
      if (event.type === 'error') throw new Error(event.message || event.error || 'Не удалось завершить обработку. Попробуйте ещё раз.');
      if (event.type === 'result') result = event.data;
      if (event.type === 'stage') {
        const id = String(event.id || event.title);
        if (!stages.has(id)) {
          const item = document.createElement('li');
          item.innerHTML = '<span class="stage-node" aria-hidden="true"></span><div><strong></strong><p></p></div><span class="stage-state"></span>';
          dialog.querySelector('.agent-stages').append(item); stages.set(id, item);
        }
        const item = stages.get(id);
        item.className = event.state === 'complete' ? 'stage-complete' : 'stage-active';
        item.querySelector('strong').textContent = event.title || 'Обрабатываем ответы';
        item.querySelector('p').textContent = event.detail || '';
        item.querySelector('.stage-node').textContent = event.state === 'complete' ? '✓' : String([...stages.keys()].indexOf(id) + 1).padStart(2, '0');
        item.querySelector('.stage-state').textContent = event.state === 'complete' ? 'Готово' : 'Сейчас';
        dialog.querySelector('.processing-status').textContent = event.title || 'Обрабатываем ответы';
      }
    };
    try {
      const response = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json', 'Accept': 'application/x-ndjson' }, body: JSON.stringify(answers), signal: controller.signal });
      if (!response.ok) {
        let error; try { error = await response.json(); } catch { /* Use Russian generic message. */ }
        throw new Error(error?.error || 'Сервис временно недоступен. Попробуйте ещё раз.');
      }
      if (!response.body) throw new Error('Не удалось прочитать ответ сервера. Обновите страницу.');
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      while (true) {
        const { done, value } = await reader.read();
        buffer += decoder.decode(value, { stream: !done });
        let end;
        while ((end = buffer.indexOf('\n')) >= 0) {
          const line = buffer.slice(0, end).trim(); buffer = buffer.slice(end + 1);
          if (line) consume(JSON.parse(line));
        }
        if (done) break;
      }
      if (buffer.trim()) consume(JSON.parse(buffer));
      if (!result) throw new Error('Сервис не завершил ответ. Попробуйте ещё раз.');
      return result;
    } catch (error) {
      if (cancelled) return null;
      if (error.name === 'AbortError') throw new Error('Обработка заняла больше времени, чем обычно. Попробуйте ещё раз или отключите ИИ-уточнение.');
      if (error instanceof TypeError || error instanceof SyntaxError) throw new Error('Не удалось связаться с сервером. Проверьте подключение и попробуйте ещё раз.');
      throw error;
    } finally { clearTimeout(timeout); closeDialog(dialog); }
  }

  function ask(question) {
    return new Promise(resolve => {
      const isLive = question.mode === 'live';
      const insight = question.insight;
      const specialOption = isLive ? [{ id: 'free_text', label: 'Отвечу своими словами', detail: 'Если готовые варианты не подходят' }] : [];
      const options = [...question.options, ...specialOption];
      const dialog = openDialog(`<div class="assistant-layout">${rail(question.signals || [])}<div class="assistant-conversation"><header class="assistant-topline"><span><i aria-hidden="true"></i> ОДНО ВАЖНОЕ УТОЧНЕНИЕ</span><button class="assistant-close" type="button" aria-label="Вернуться к анкете">×</button></header><div class="assistant-speaker">${mark}<div><strong>Ассистент PRIME</strong><small>${escape(modes[question.mode] || 'Подбор по правилам')}</small></div><span class="assistant-step">1 / 1</span></div>${question.mode === 'fallback' ? '<p class="agent-fallback" role="status">Не удалось получить проверенное ИИ-уточнение. Для вас подготовлен вопрос по правилам.</p>' : ''}${insight ? `<div class="connection-card"><span>ЗАМЕЧЕННАЯ СВЯЗЬ</span><h3>${escape(insight.title)}</h3><p>${escape(insight.connection)}</p>${insight.missing_detail ? `<small>Уточним: ${escape(insight.missing_detail)}</small>` : ''}</div>` : ''}<p class="assistant-context">${escape(question.context)}</p><h2 id="assistant-question" tabindex="-1">${escape(question.question)}</h2><form class="assistant-answer-form" novalidate><fieldset class="assistant-options"><legend class="assistant-sr-only">Выберите один ответ</legend>${options.map((option, index) => `<label class="assistant-option ${option.id === 'free_text' ? 'option-free' : ''}"><input type="radio" name="clarification_option" value="${escape(option.id)}"><span class="option-body"><span class="option-number" aria-hidden="true">${String(index + 1).padStart(2, '0')}</span><span><strong>${escape(option.label)}</strong>${option.detail ? `<small>${escape(option.detail)}</small>` : ''}</span><span class="option-check" aria-hidden="true">✓</span></span></label>`).join('')}</fieldset><details class="assistant-extra"><summary>Добавить своими словами <span aria-hidden="true">＋</span></summary><label class="assistant-sr-only" for="assistant-detail">Дополнение к ответу</label><textarea id="assistant-detail" maxlength="500" rows="2" placeholder="${escape(question.placeholder || 'Напишите то, что важно знать врачу')}"></textarea><span class="assistant-counter">0 / 500</span></details><div class="assistant-why"><span aria-hidden="true">↳</span><p><strong>Почему спрашиваю</strong>${escape(question.why)}</p></div><footer class="assistant-actions"><button class="assistant-skip" type="button">Пропустить уточнение</button><button class="button button-primary assistant-confirm" type="submit" disabled>Учесть ответ <span aria-hidden="true">↗</span></button></footer><p class="assistant-boundary">Виртуальный помощник не ставит диагноз. План подтвердит врач.</p></form></div></div>`, 'assistant-question');
      let settled = false;
      const finish = value => { if (settled) return; settled = true; closeDialog(dialog); resolve(value); };
      dialog.querySelector('.assistant-close').addEventListener('click', () => finish(null));
      dialog.addEventListener('cancel', event => { event.preventDefault(); finish(null); });
      dialog.querySelector('.assistant-skip').addEventListener('click', () => finish({ question_id: question.id, skipped: true, token: question.token }));
      const answerForm = dialog.querySelector('form');
      const confirm = dialog.querySelector('.assistant-confirm');
      const detail = dialog.querySelector('#assistant-detail');
      const update = () => {
        const option = answerForm.elements.clarification_option.value;
        confirm.disabled = !option || (option === 'free_text' && detail.value.trim().length < 3);
        dialog.querySelector('.assistant-counter').textContent = `${detail.value.length} / 500`;
      };
      answerForm.addEventListener('change', () => {
        if (answerForm.elements.clarification_option.value === 'free_text') { dialog.querySelector('.assistant-extra').open = true; detail.focus(); }
        update();
      });
      detail.addEventListener('input', update);
      answerForm.addEventListener('submit', event => {
        event.preventDefault(); update();
        if (!confirm.disabled) finish({ question_id: question.id, option_id: answerForm.elements.clarification_option.value, detail: detail.value.trim(), skipped: false, token: question.token });
      });
    });
  }

  function receipt(value, compact = false) {
    if (!value) return '';
    if (value.skipped) return `<div class="assistant-skipped">${mark}<p>Уточнение пропущено. Врач сможет задать этот вопрос на приёме.</p></div>`;
    const delta = value.before && value.after;
    return `<article class="insight-receipt ${compact ? 'receipt-compact' : ''}"><div class="receipt-intro">${mark}<div><span>${compact ? 'ЗАПИСКА ДЛЯ ВРАЧА' : 'ОДИН ОТВЕТ. БОЛЬШЕ ЯСНОСТИ.'}</span><h3>${escape(value.impact_title)}</h3></div><span class="receipt-tag">${value.mode === 'live' ? 'ИИ-уточнение учтено' : 'Уточнение учтено'} ✓</span></div>${delta ? `<div class="plan-delta"><div class="delta-before"><small>ДО УТОЧНЕНИЯ</small><p>${escape(value.before)}</p></div><span class="delta-arrow" aria-hidden="true">↗</span><div class="delta-after"><small>ТЕПЕРЬ В ВАШЕМ ПЛАНЕ</small><p>${escape(value.after)}</p></div></div>` : ''}<div class="receipt-grid"><div><small>Вопрос по анкете</small><p>${escape(value.question)}</p></div><div class="receipt-answer"><small>Вы уточнили</small><strong>${escape(value.answer_label)}</strong>${value.detail ? `<p class="receipt-quote">«${escape(value.detail)}»</p>` : ''}</div><div><small>Что меняется в плане</small><p>${escape(value.impact)}</p></div></div><div class="receipt-foot"><span>↳ ${escape(value.clinician_note)}</span>${compact || value.action !== 'continue' ? '' : '<a href="#health-card">В карте здоровья ↗</a>'}</div></article>`;
  }
  window.PrimeAssistant = { run, ask, receipt };
})();
