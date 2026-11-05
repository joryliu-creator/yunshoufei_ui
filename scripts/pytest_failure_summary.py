"""Persist compact results as each pytest phase finishes."""
import json
from pathlib import Path
from urllib.parse import urlsplit

_ATTACHED_PAGE_IDS: set[int] = set()


def pytest_sessionstart(session):
    _ATTACHED_PAGE_IDS.clear()


def pytest_runtest_call(item):
    page = item.funcargs.get('page') or item.funcargs.get('fresh_login_page')
    if page is None or id(page) in _ATTACHED_PAGE_IDS:
        return
    _ATTACHED_PAGE_IDS.add(id(page))
    def emit(record):
        folder = Path('artifacts')
        folder.mkdir(exist_ok=True)
        with (folder / 'browser-errors.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + '\n')
    page.on('pageerror', lambda error: emit({'pageerror': str(error)}))
    page.on('requestfailed', lambda request: emit({'failed_path': urlsplit(request.url).path, 'error': request.failure}))
    def response_info(response):
        path = urlsplit(response.url).path
        if any(word in path.lower() for word in ('create', 'save', 'addbill')):
            data = {'path': path, 'status': response.status}
            try:
                body = response.json()
                if isinstance(body, dict):
                    data['result'] = {key: body[key] for key in ('code', 'message', 'msg', 'success') if key in body}
            except Exception:
                pass
            emit(data)
    page.on('response', response_info)

def pytest_runtest_logreport(report):
    if report.when != 'call' and not report.failed:
        return
    crash = getattr(report.longrepr, 'reprcrash', None)
    record = {'nodeid': report.nodeid, 'phase': report.when,
              'outcome': report.outcome, 'duration': report.duration,
              'error': str(getattr(crash, 'message', '')),
              'properties': list(report.user_properties)}
    folder = Path('artifacts')
    folder.mkdir(exist_ok=True)
    with (folder / 'live-results.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + '\n')
