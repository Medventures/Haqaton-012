"""Opt-in end-to-end browser check with synthetic data and real server AI calls.

Unlike browser_smoke.py, this script does not mock the agent. It never reads an API
key. The configured server makes billable provider requests after --live approval.
Screenshots contain only the fictional scenario embedded here.
"""
import argparse
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_smoke import chrome_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8010')
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--screenshot-dir', default='.qa-screenshots')
    args = parser.parse_args()
    if not args.live:
        parser.error('Добавьте --live для платной проверки реального агента.')
    if urlsplit(args.base_url).hostname not in ('localhost', '127.0.0.1'):
        parser.error('Этот сценарий рассчитан на локальный тестовый сервер.')
    output = Path(args.screenshot_dir)
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=chrome_path(None), headless=True,
            args=['--no-sandbox', '--disable-gpu', '--disable-gpu-sandbox', '--disable-software-rasterizer', '--disable-features=Vulkan,UseSkiaRenderer'])
        context = browser.new_context(viewport={'width':1440, 'height':1100}, locale='ru-RU', reduced_motion='reduce')
        page = context.new_page()
        page.add_init_script("""(() => {
          const original = window.fetch.bind(window);
          window.__qaAgentResponses = {};
          window.fetch = async (...args) => {
            const response = await original(...args);
            const url = String(args[0]);
            if (url.startsWith('/api/agent/')) response.clone().text().then(text => {
              window.__qaAgentResponses[url] = text.split('\\n').filter(Boolean).map(line => JSON.parse(line));
            });
            return response;
          };
        })();""")
        errors = []
        page.on('pageerror', lambda error: errors.append(type(error).__name__))
        # Keep synthetic QA clicks out of production product counters.
        page.route('**/api/events', lambda route: route.fulfill(status=202, json={'status':'ok'}))
        page.goto(args.base_url)
        page.locator('#age').fill('32')
        page.locator('label:has(input[name="sex"][value="male"])').click()
        page.locator('#concerns label:has(input[value="fatigue"])').click()
        page.locator('#notes').fill('Работаю две ночи через две. В выходные сплю ночью, но усталость не всегда проходит.')
        page.locator('[name="ai_consent"]').check()
        with page.expect_response(lambda r: r.url.endswith('/api/agent/clarify'), timeout=120000) as question_response:
            page.locator('#submit-button').click()
            expect(page.locator('#processing-title')).to_be_visible()
            expect(page.locator('.agent-stages li').first).to_be_visible(timeout=20000)
            page.screenshot(path=str(output/'live-processing.png'))
            expect(page.locator('#assistant-question')).to_be_visible(timeout=120000)
        page.wait_for_function("window.__qaAgentResponses['/api/agent/clarify']")
        question_events = page.evaluate("window.__qaAgentResponses['/api/agent/clarify']")
        question = next(event['data'] for event in question_events if event['type']=='result')
        assert question['mode']=='live', question.get('audit',{}).get('failure_code','not_live')
        assert question['audit']['verified']
        assert len(question['audit']['tool_names'])==3
        page.screenshot(path=str(output/'live-question.png'))
        option = next((item for item in question['options'] if any(word in item['label'].casefold() for word in ('не знаю','не уверен','сложно','не помню','не сравнивал','не замечал','затрудняюсь','не могу сказать','не отслеживал','не обращал внимания','не обсуждали'))), None)
        assert option is not None, 'No explicit uncertainty option in live question'
        page.locator(f'dialog label:has(input[value="{option["id"]}"])').click()
        with page.expect_response(lambda r: r.url.endswith('/api/agent/recommend'), timeout=120000) as recommendation_response:
            page.locator('.assistant-confirm').click()
            expect(page.locator('#recommendation .plan-delta')).to_be_visible(timeout=120000)
        page.wait_for_function("window.__qaAgentResponses['/api/agent/recommend']")
        result_events=page.evaluate("window.__qaAgentResponses['/api/agent/recommend']")
        result=next(event['data'] for event in result_events if event['type']=='result')
        (output/'live-result.json').write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
        clarification=result['clarification']
        assert clarification['mode']=='live', clarification.get('audit',{}).get('failure_code','not_live')
        assert clarification['audit']['verified']
        expect(page.locator('#health-card .receipt-compact')).to_contain_text(clarification['after'])
        page.locator('#recommendation').scroll_into_view_if_needed()
        page.screenshot(path=str(output/'live-plan.png'))
        page.set_viewport_size({'width':390,'height':844})
        overflow=page.evaluate("[...document.querySelectorAll('body *')].filter(el=>el.getBoundingClientRect().right>innerWidth+1).slice(0,10).map(el=>({tag:el.tagName,id:el.id,class:el.className}))")
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), overflow
        page.locator('#recommendation .plan-delta').scroll_into_view_if_needed()
        page.screenshot(path=str(output/'live-mobile-plan.png'))
        print(json.dumps({'ok':not errors,'question_mode':question['mode'],'handoff_mode':clarification['mode'],
            'calls':clarification['audit']['calls'],'tools':clarification['audit']['tool_names'],
            'question':question['question'],'before':clarification['before'],'after':clarification['after'],
            'browser_errors':errors},ensure_ascii=True))
        context.close(); browser.close()
    return 0 if not errors else 1


if __name__=='__main__':
    raise SystemExit(main())
