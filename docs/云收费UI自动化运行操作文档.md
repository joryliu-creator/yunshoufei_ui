# 云收费 UI 自动化运行操作文档

本文用于本地执行和 Jenkins 定时执行云收费 UI 回归。项目使用 Python、pytest、Playwright 和 Page Object；测试数据从回归 Excel 及环境配置读取。

## 一、首次准备

在项目根目录 `D:\\lz\\autotest` 执行：

```powershell
python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium
```

每个环境使用独立配置文件：

```text
.env.standard1
.env.standard2
.env.uat
.env.prod.example   # 生产只保留示例，禁止执行副作用用例
```

至少需要配置环境地址、客户号和账号凭据。真实账号、密码、验证码和 `.auth` 登录态只放本机或 Jenkins Credentials，不提交 Git：

```dotenv
TEST_ENV=standard1
BASE_URL=http://t.jslife.net/jportal/index.html
CUSTOMER_ID=93537
C93537_DEFAULT_USERNAME=<本地或 Jenkins Secret>
C93537_DEFAULT_PASSWORD=<本地或 Jenkins Secret>
C93537_DEFAULT_CAPTCHA=0000
ALLOW_BILL_CREATION=true
CLEANUP_CREATED_BILL=true
ALLOW_BILL_DELETION=true
```

如尚未保存登录态，本地执行一次（会打开有头浏览器）：

```powershell
.\\.venv\\Scripts\\python.exe scripts\\save_auth.py `
  --environment standard1 --customer-id 93537 --account default
```

登录态保存到 `.auth/<环境>/<客户号>/<账号别名>/`。登录提示“账号在其他地方登录”时，按正常流程再次提交一次，随后重新请求带客户号的 `#/Home` 地址；测试脚本也会按此规则自动恢复。

## 二、本地执行

### 1. 只检查用例收集，不访问页面

```powershell
.\\.venv\\Scripts\\python.exe scripts\\run_jenkins_regression.py `
  --test-env standard1 --customer-id 93537 --collect-only --skip-post-cleanup
```

当前回归清单应收集到 102 条用例。

### 2. 首次冒烟：只跑一条

```powershell
.\\.venv\\Scripts\\python.exe scripts\\run_jenkins_regression.py `
  --test-env standard1 --customer-id 93537 --account-role default `
  --test-target "tests/billing/test_create_periodic_center_bills.py::test_create_periodic_bill_and_cleanup[chromium-YSF-BILL-PERIODIC-1002]"
```

该命令验证登录、房间/收费项选择、金额断言、账单编号读取、作废删除和报告生成。

### 3. 本地跑全部已实现账单用例

```powershell
.\\.venv\\Scripts\\python.exe scripts\\run_jenkins_regression.py `
  --test-env standard1 --customer-id 93537 --account-role default `
  --max-minutes 0
```

默认执行 `tests/billing` 下全部用例，使用无头 Chromium、串行执行，并在每条用例后清理创建的数据。`--max-minutes 0` 表示本地不设置总时长上限；不传时默认 50 分钟保护。

如需观察浏览器：

```powershell
.\\.venv\\Scripts\\python.exe scripts\\run_jenkins_regression.py `
  --test-env standard1 --customer-id 93537 --headed --slowmo 300
```

### 4. 直接使用 pytest（不推荐作为常规入口）

```powershell
.\\.venv\\Scripts\\python.exe -m pytest tests/billing -v `
  --test-env standard1 --customer-id 93537 --account-role default
.\\.venv\\Scripts\\python.exe scripts\\generate_html_report.py
```

本地默认不生成 JUnit，仅保留控制台日志和 HTML 报告。

如需给 Jenkins 提供机器可读结果，增加 `--junit --junitxml artifacts/local-junit.xml`；本地查看通常不需要 JUnit。

统一入口脚本更适合日常使用，因为它会在 pytest 结束后执行补偿清理并生成固定报告。

## 三、Jenkins 定时执行

Jenkins Windows 节点需要准备 Python、虚拟环境、Chromium、对应 `.env.<环境>` 和 `.auth` 登录态。建议使用 Jenkins Credentials 注入账号密码环境变量，不要把密码写入 Jenkinsfile 或仓库。

### 推荐的 Jenkins 构建命令

```powershell
Set-Location 'D:\\lz\\autotest'
.\\.venv\\Scripts\\python.exe scripts\\run_jenkins_regression.py `
  --test-env standard1 `
  --customer-id 93537 `
  --account-role default `
  --max-minutes 0 `
  --junit
```

Jenkins 中配置：

1. 定时触发器（按团队要求设置时间）。
2. 构建步骤执行上面的 PowerShell 命令。
3. 发布 JUnit：`artifacts/jenkins-junit.xml`。
4. 发布 HTML：归档 `artifacts` 目录，重点查看 `jenkins-regression-report.html`。
5. 保留 `test-results/` 和 `playwright-report/`，便于失败时查看截图、视频和 trace。

### 用例较多时分片

如果希望多个 Jenkins 任务错峰或并行运行，可建立 4 个任务，分别使用：

```powershell
--shard-count 4 --shard-index 0
--shard-count 4 --shard-index 1
--shard-count 4 --shard-index 2
--shard-count 4 --shard-index 3
```

每个分片仍然串行执行，报告会自动写入：

```text
artifacts/jenkins-junit-shard-1.xml
artifacts/jenkins-regression-report-shard-1.html
```

其余分片编号依次递增。

## 四、本机每天晚上自动执行（不使用 Jenkins）

项目已提供本机包装脚本：

```text
scripts/run_nightly_regression.ps1
```

脚本固定使用标准1、客户号 93537、`default` 账号，以无头模式执行全部账单用例；日志写入 `artifacts/scheduler-logs/`，报告写入 `artifacts/`。

在 Windows“任务计划程序”中创建任务：

1. 选择“创建任务”，名称填写“云收费 UI 夜间回归”。
2. “触发器”新增“每天”，设置晚上执行时间，例如 23:00。
3. “操作”选择“启动程序”：
   - 程序：`powershell.exe`
   - 参数：`-NoProfile -ExecutionPolicy Bypass -File "D:\\lz\\autotest\\scripts\\run_nightly_regression.ps1"`
   - 起始于：`D:\\lz\\autotest`
4. “常规”建议选择“无论用户是否登录都运行”，使用拥有项目目录权限的 Windows 账号；不需要勾选“最高权限”。
5. “条件”中如电脑可能休眠，勾选“唤醒计算机运行此任务”；“设置”中勾选失败后按需重试。
6. 先右键任务选择“运行”测试一次，确认日志、HTML 报告和账单清理均正常，再启用每天触发。

也可以使用任务管理脚本快速配置或切换任务：

```powershell
# 创建并启用每天 23:00 的任务
C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe -NoProfile -ExecutionPolicy Bypass -File "D:\\lz\\autotest\\scripts\\manage_nightly_task.ps1" -Action install -Time 23:00

# 启用、暂停、立即运行、查看状态、删除
C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe -NoProfile -ExecutionPolicy Bypass -File "D:\\lz\\autotest\\scripts\\manage_nightly_task.ps1" -Action enable
C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe -NoProfile -ExecutionPolicy Bypass -File "D:\\lz\\autotest\\scripts\\manage_nightly_task.ps1" -Action disable
C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe -NoProfile -ExecutionPolicy Bypass -File "D:\\lz\\autotest\\scripts\\manage_nightly_task.ps1" -Action run
C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe -NoProfile -ExecutionPolicy Bypass -File "D:\\lz\\autotest\\scripts\\manage_nightly_task.ps1" -Action status
C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe -NoProfile -ExecutionPolicy Bypass -File "D:\\lz\\autotest\\scripts\\manage_nightly_task.ps1" -Action remove
```

该脚本按当前 Windows 用户注册任务，电脑在计划时间保持登录即可。若必须在未登录时运行，请在任务计划程序界面手动配置 Windows 凭据，不要把系统密码写入脚本。

任务计划程序运行的是无头浏览器，不会弹出 Chrome 窗口。电脑必须能访问测试环境，且该 Windows 账号下已存在对应 `.env.standard1` 和 `.auth/standard1/93537/default/`。真实密码不要写入脚本或提交仓库。

## 五、清理规则

- 账单中心直接创建：创建成功后立即记录唯一账单编号，按编号执行作废、删除和不存在复查。
- 计费出账审核通过：回到账单中心，以账期 + 房间 + 未作废 + 收费项/金额唯一定位后，再读取账单编号并作废、删除。
- 临时类账单：临时类和押金类收费项产生的账单均属于临时类账单；计费出账和临时台账使用各自入口的清理流程。
- 生成、核对或审核中途失败：`finally` 先清理待处理卡片；入口脚本结束后还会补偿清理待处理卡片和临时类账单。
- 清理开关必须同时开启：`CLEANUP_CREATED_BILL=true`、`ALLOW_BILL_DELETION=true`。任何一个关闭，都不能宣称“已清理”。
- 生产环境禁止创建、作废和删除副作用数据。

## 六、报告说明

HTML 报告包含用例编号、环境、场景、房间、收费项、预期金额、实际金额、通过状态、清理结果和失败详情。单条冒烟运行时，报告仍会列出完整场景清单，未执行的场景标记为“未执行”，不能误认为已通过。

## 七、常见问题

**提示未找到登录态**：在同一环境、客户号和账号别名下重新执行 `save_auth.py`；Jenkins 节点必须单独保存 `.auth`，本机的 `.auth` 不会随 Git 同步。

**页面加载慢**：保持串行执行，不要用坐标强制点击；脚本会等待 iframe、房间树、收费项树和金额计算完成。失败后优先查看 `test-results/` 的截图和 trace。

**账单重复无法创建**：先运行入口脚本的补偿清理，或在确认范围后执行：

```powershell
.\\.venv\\Scripts\\python.exe scripts\\cleanup_calculation_pending.py
.\\.venv\\Scripts\\python.exe scripts\\cleanup_calculation_temporary_bills.py
```

清理后再重新执行失败用例，避免通过重试重复提交同一账期账单。
