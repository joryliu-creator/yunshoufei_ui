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

### 收费标准初始化

新环境首次初始化时，先按房间映射表创建业务收费标准；脚本默认使用映射表中的业务名称，不添加 `AT-` 前缀：

```powershell
.\\.venv\\Scripts\\python.exe scripts\\create_charge_standards.py `
  --environment <新环境名> --customer-id <客户号> --account default `
  --project 云收费UI自动化 --rooms 1001 1002 1003 `
  --fresh-login --delete-created-on-failure
```

自动化专项验证才使用 `--automation-names` 创建 `AT-` 测试收费标准；业务初始化和自动化测试数据必须分开。

公摊验证房间使用以下脚本追加到房间导入模板；脚本会幂等检查房间号，参与公摊房间的收费项保持为空：

```powershell
.\\.venv\\Scripts\\python.exe scripts\\add_public_share_rooms.py
```

该脚本同时维护所有计费面积相关公摊的 19 对专用房间，并将每对房间的建筑面积/使用面积写成不同组合；
收费面积仍需通过房间收费配置维护，不能用模板中的建筑面积或使用面积代替。

周期类公摊方案属于新环境初始化基线。创建 5 个正式方案时使用以下脚本；方案名称不带
`AT-` 前缀，脚本只创建/校验，不执行删除，后续账单出账场景可直接引用这些方案：

```powershell
.\\.venv\\Scripts\\python.exe scripts\\create_initial_public_share_schemes.py `
  --allow-initialization --test-env standard1 --customer-id 93537 `
  --account-role default --project 云收费UI自动化
```

初始化方案与回归专项方案严格分开：初始化方案不清理；回归专项使用 `AT-` 前缀，并由
独立清理用例按精确名称删除。

如果系统重新下载的房间模板结构发生变化，先使用同目录的原始模板恢复结构，再保留当前房间数据：

```powershell
.\\.venv\\Scripts\\python.exe scripts\\restore_room_template_from_original.py
```

恢复脚本先复制 `前置数据模版文件/房间导入模版-原始模版.xlsx` 生成工作副本，再迁移 `房间导入模版.xlsx` 中现有房间数据；工作副本的表头、列宽、单元格格式和数据验证均以原始模板为准。

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

- 账单中心直接创建、计费出账审核通过：统一回到账单中心按账期 + 房间 + 收费项查询。新版高级搜索中“收费对象”决定账单归属主体，先切换为“收费对象-房间”，再在相邻房间树选择房间；“关联对象”是关联资产的可选附加条件，按房间清理时留空。核对金额/状态并确认唯一命中本次账单；账单编号仅作报告证据或结果行身份核对，不得作为筛选条件。账单中心先填写作废原因并“更多/批量作废”，再“更多/批量删除”，最后按相同业务键复查为 0 条；结果不唯一时停止并报告。
- 临时类/押金类账单：计费出账产生的账单审核出账后进入账单中心，按账期 + 房间 + 收费项定位并批量作废、批量删除；临时台账直接产生的账单只在临时台账，按相同业务键定位后行内作废、行内删除。两种入口不可混用清理动作。
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
# Docker 服务器运行补充（2026-09-04）

服务器 `10.10.209.20` 的运行入口为
`/home/jht/cloud-billing-ui-automation/app/scripts/run_server_docker_regression.sh`。
默认使用离线镜像 `cloud-billing-ui-test:1.3`，执行输出保存在
`/home/jht/cloud-billing-ui-automation/artifacts`。

Docker 不会继承宿主机的 `/etc/hosts`。标准1门户在宿主机解析为
`10.10.203.14`，原容器却解析为公网 `218.17.23.103`，造成 Chromium
以 `ERR_BLOCKED_BY_LOCAL_NETWORK_ACCESS_CHECKS` 拒绝加载内网业务 iframe。
启动脚本已固定传入 `--add-host t.jslife.net:10.10.203.14`；切换部署地址时通过
`AUTOMATION_PORTAL_HOST` 和 `AUTOMATION_PORTAL_IP` 覆盖，不要关闭浏览器整体安全检查。

启动脚本同时只读挂载 `app/.auth`，以读取按环境、客户、角色隔离的登录状态。
`.env.standard1` 与 `.auth` 属于私密运行配置，不打入镜像或提交仓库。
仪表用例采集需要 `前置数据模版文件/线下仪表用量导入模板.xlsx`，该文件必须随安装包提供。

手动运行全部场景：

```bash
bash /home/jht/cloud-billing-ui-automation/app/scripts/run_server_docker_regression.sh
```

运行全量回归场景：

```bash
bash /home/jht/run_server_representative_chain.sh
```

仅运行 8 条代表性场景：

```bash
bash /home/jht/run_server_8_representative_chain.sh
```

该一键脚本已包含 Docker、内网域名映射、环境配置、登录状态和报告目录挂载，首次复制到服务器后执行：

```bash
chmod +x /home/jht/cloud-billing-ui-automation/app/scripts/run_server_representative_chain.sh
```

全量 HTML 报告位于 `$BASE/artifacts/server-regression-report.html`，8 条专项报告位于
`$BASE/artifacts/representative-chain.html`。可用 `scp` 下载到本机后
直接用浏览器打开；明细日志为 `live-results.jsonl` 和 `browser-errors.jsonl`。

从服务器下载 HTML 报告到本地（在本机 PowerShell 执行）：

```powershell
scp -i C:\Users\Administrator\.ssh\codex_jenkins_20260903 `
  jht@10.10.209.20:/home/jht/cloud-billing-ui-automation/artifacts/server-regression-report.html `
  .\server-regression-report.html

scp -i C:\Users\Administrator\.ssh\codex_jenkins_20260903 `
  jht@10.10.209.20:/home/jht/cloud-billing-ui-automation/artifacts/representative-chain.html `
  .\representative-chain.html
```

下载完成后，双击本地 HTML 文件即可用浏览器查看。

可在命令后重复传入 `--test-target '完整pytest节点ID'` 选择多个场景。
多个目标在同一 pytest 会话中按账单中心、计费出账、临时台账排序；保留逐条清理、
模块间清理和最终检查。`scripts/run_representative_chain.py` 固定选取八个代表场景，
先预检节点再实际执行，临时台账节点只选一条参数化用例。

本次排障已用相同容器对照确认：补映射前业务 iframe 被拦截，补映射后业务 iframe
能加载。这一结果只证明页面访问修复；出账、金额与清理结果以实际回归报告为准。

每条用例的即时结果写入 `artifacts/live-results.jsonl`，浏览器异常及创建接口反馈
写入 `artifacts/browser-errors.jsonl`。两者追加记录，排查时以本轮新增记录为准。
收费项选择等待左侧真实树节点后才输入名称；最晚缴款日按 Excel“执行当天”动态取值，
账期仍固定 `2026-08`。

2026-09-04 剩余阻塞：房间 1002 创建接口提示 2026-08 计费期间与已生成明细交叉，
而 `queryBillByPage` 在项目 `p202603190`、全年账期、无状态限制条件下成功返回
`total=0`。这组响应不能作为“创建并清理通过”的证据；需要后端核对明细与账单的关联，
不得自动删除无法在授权业务列表中确认的记录。
