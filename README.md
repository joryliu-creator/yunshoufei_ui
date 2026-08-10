# 云收费 UI 自动化回归 Demo

当前项目已改为 **Python + pytest + Playwright**，并采用 Page Object（PO）设计模式。

Demo 对应用例 `YSF-BILL-001`：在“云收费自动化MS1”项目的账单中心，为房间“云收费自动化MS/1/周期性收费房间001”创建 7 月周期性账单；提交后选择“不需要”发送通知。根据配置，还可以自动作废并删除本次新建的账单。

## 目录结构

```text
src/config/settings.py                         环境变量与测试数据
src/config/accounts.py                         账号别名与独立登录态路径
src/pages/base_page.py                         Page Object 公共能力
src/pages/portal_page.py                       门户首页 Page Object
src/pages/billing_center_page.py               账单中心 Page Object
tests/billing/test_create_periodic_bill.py     业务测试用例
conftest.py                                    按账号别名创建独立浏览器上下文
scripts/save_auth.py                           保存指定账号的登录状态
pytest.ini                                     pytest-playwright 配置
UI自动化回归测试用例模板_Demo.xlsx             Demo 用例和测试数据
```

## 初始化

在 PowerShell 中执行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium
Copy-Item .env.example .env
```

不要把账号、密码或验证码写入代码、Excel 或提交到仓库。

## 保存登录状态

默认账号执行：

```powershell
python scripts/save_auth.py --account default
```

其他账号按别名执行：

```powershell
python scripts/save_auth.py --account billing_admin
python scripts/save_auth.py --account cashier
python scripts/save_auth.py --account finance_admin
```

脚本优先读取本地 `.env` 中与别名对应的凭据，例如 `BILLING_ADMIN_USERNAME` 和 `BILLING_ADMIN_PASSWORD`。未配置凭据时可以在打开的浏览器中人工登录。登录状态分别保存到 `.auth/<账号别名>/`，该目录已被忽略。

Excel 和代码只保存账号别名，不保存真实账号、密码或验证码。

## 运行 Demo

此用例会新增真实测试账单，默认处于跳过状态。确认项目、房间、收费项和账期均可用于测试后，在 `.env` 设置：

```dotenv
ALLOW_BILL_CREATION=true
```

运行：

```powershell
pytest tests/billing/test_create_periodic_bill.py -v
```

临时指定该次运行使用的账号：

```powershell
pytest tests/billing/test_create_periodic_bill.py -v --account-role billing_admin
```

单条用例也可以声明账号：

```python
@pytest.mark.account("billing_admin")
def test_example(page):
    ...
```

同一端到端用例需要多个账号时，使用 `account_context` 创建互相隔离的上下文：

```python
def test_cross_role_flow(account_context):
    billing_page = account_context("billing_admin").new_page()
    cashier_page = account_context("cashier").new_page()
```

调试时显示浏览器：

```powershell
pytest tests/billing/test_create_periodic_bill.py -v --headed --slowmo 300
```

## 自动清理账单

创建成功后自动执行“作废 → 填写作废理由 → 勾选账单 → 更多 → 批量删除 → 确定”，必须同时打开两个安全开关：

```dotenv
CLEANUP_CREATED_BILL=true
ALLOW_BILL_DELETION=true
VOID_REASON=UI自动化Demo数据清理
```

清理仅使用本次运行读取到的账单编号定位。定位不到或匹配到多条时会立即失败，不会扩大删除范围。

## 安全与稳定性设计

- 创建与删除分别使用独立环境变量授权，默认都关闭。
- 每个账号别名使用独立 browser context、storage state 和 sessionStorage，防止账号串用。
- 提交前校验收费周期必须以 `BILLING_MONTH` 开头，防止界面显示 7 月但实际生成 8 月账单。
- 页面元素操作集中在 Page Object 中；测试文件只组织业务流程和断言。
- 失败时由 pytest-playwright 保留截图、视频和 Trace，输出位于 `test-results/`。
- 退款等资金操作不纳入自动执行范围。

## 扩展约定

- 一个业务页面对应一个 `*_page.py`。
- 一个业务场景对应一个 `test_*.py`。
- 环境差异和可变测试数据统一放在 `.env`，不要写死账号密码。
- 新增、修改、通知、作废、删除等副作用操作必须配置显式安全开关。
