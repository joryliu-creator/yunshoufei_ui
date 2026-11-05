"""Read-only portal/iframe network diagnostic; never outputs credentials."""
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from playwright.sync_api import sync_playwright
from src.config.settings import settings
from src.pages.portal_page import PortalPage

def safe_url(url):
    part = urlsplit(url)
    return f"{part.scheme}://{part.netloc}{part.path}"

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    page = browser.new_page()
    def bill_response(response):
        path = urlsplit(response.url).path
        if not path.endswith(('/queryBillByPage', '/getBillCenterStatistic')):
            return
        try:
            body = response.json()
            request = response.request.post_data_json
            summary = {key: body.get(key) for key in ('resultCode', 'message', 'success')}
            data = body.get('respData') or {}
            if isinstance(data, dict):
                summary['total'] = data.get('total')
            print('bill_api', json.dumps({'path': path, 'request': request, 'response': summary}, ensure_ascii=False), flush=True)
        except Exception:
            pass
    if '--bill-residue' in sys.argv:
        page.on('response', bill_response)
    page.on('requestfailed', lambda req: print(json.dumps({'failed': safe_url(req.url), 'error': req.failure}, ensure_ascii=False), flush=True))
    portal = PortalPage(page)
    portal.open_home(settings.base_url, settings.master_customer_id, environment=settings.test_environment, account_role='default')
    portal.open_billing_center()
    page.wait_for_timeout(10000)
    for src in page.locator('iframe').evaluate_all('(els) => els.map(e => e.src)'):
        print('iframe_src', safe_url(src), flush=True)
    print('frames', [safe_url(f.url) for f in page.frames], flush=True)
    if '--bill-residue' in sys.argv:
        from src.pages.billing_center_page import BillingCenterPage
        billing = BillingCenterPage(page)
        billing.wait_until_ready()
        billing.select_project(settings.project_name)
        page.wait_for_timeout(3000)
        print('bill_list', billing.frame.locator('body').inner_text()[:16000], flush=True)
    if '--charge-picker' in sys.argv:
        from src.pages.billing_center_page import BillingCenterPage, BillData
        billing = BillingCenterPage(page)
        billing.wait_until_ready()
        billing.select_project(settings.project_name)
        drawer = billing.open_create_bill()
        if '--inspect-picker' in sys.argv:
            def inspect_picker(dialog, item):
                dialog.get_by_text('新增收费项', exact=True).click()
                page.wait_for_timeout(1500)
                picker = billing.frame.locator('.el-drawer:visible').last
                picker.locator('input.el-input__inner:visible:not([readonly]):not([disabled])').first.fill(item)
                page.wait_for_timeout(1500)
                raise RuntimeError('Read-only picker inspection; no bill submitted')
            billing._add_charge_item = inspect_picker
        try:
            billing.fill_bill(drawer, BillData(project_name=settings.project_name,
                room_path='A栋/1层/1002', charge_type='周期类', charge_item='UI周期性收费项',
                billing_month='2026-08', receivable_date='2026-08-01',
                latest_payment_date='2026-09-04'))
        except Exception as exc:
            print(type(exc).__name__, str(exc)[:800], flush=True)
        folder = ROOT / 'artifacts'
        folder.mkdir(exist_ok=True)
        drawers = billing.frame.locator('.el-drawer:visible')
        (folder / 'server-charge-picker.html').write_text(drawers.last.inner_html(), encoding='utf-8')
        print('picker_diagnostic_saved', flush=True)
    browser.close()
