---
name: billing-center-ui-automation
description: 为天启标准云收费 Web 应用设计、生成、调整和验证 Python Playwright UI 自动化脚本及 Excel 回归用例。用于账单中心及相邻业务场景，尤其适合在本项目现有 Page Object、pytest、登录状态复用、Element UI 弹窗/树/iframe 处理、安全作废删除和测试数据参数化基础上新增场景，或把人工操作步骤同步为可执行脚本与用例；产品业务语义和通用安全规则由 cloud-billing-product-knowledge 提供。
---

For temporary-billing room lookup, read
`references/temporary-billing-room-routing.md` when that scenario applies.
Read `$cloud-billing-product-knowledge` for the product-defined Temporary
Ledger cleanup workflow.

## Universal login recovery rule

This rule applies to every cloud-billing UI automation scenario, not only
temporary billing:

- Use the configured local credentials for the selected environment, customer,
  and account role; never hard-code credentials in tests, Excel, or skill text.
- If login succeeds but Standard1 shows the transient message that the account
  is logged in elsewhere, do not immediately mark login as failed. Submit the
  login once more, request `#/Home?masterCustomerId=<customer>` explicitly,
  dismiss overlays, and verify the portal/business menu.
- If the second recovery still cannot reach the portal, stop and report the
  login blocker. Do not loop indefinitely or create business data while login
  state is uncertain.
- Saved cookies/sessionStorage are an optimization only. If they are expired,
  fall back to the normal credential-login path; a stale snapshot is not proof
  that the account is unavailable.

# 账单中心 UI 自动化

## 目标

基于本仓库已经真实跑通的 Demo 新增回归场景。保持 Python + Playwright 同步 API + pytest + Page Object 结构，并让脚本、Excel 用例和最终人工确认步骤一致。产品业务知识不在本 Skill 重复定义，以 `$cloud-billing-product-knowledge` 为唯一公共来源。

对陌生业务，默认由熟悉业务的测试人员主导首次探索和正确性判断。AI独立探索因缺少隐含业务知识和存在工具调用延迟，通常慢于熟练人工；本 Skill 的主要价值是将人工确认后的步骤快速转化为结构化用例、脚本、数据和可复用规则，并辅助后续重复回归与失败分析。

## 节省 Token 执行基准

- 日常新增用例、Page Object 修改、Excel 参数化、稳定脚本维护和普通失败分析，默认使用 GPT-5.6 Luna，以节省 token；已验证的简单变更、Excel 机械维护和文档整理也使用 Luna。
- 需要跨 iframe/弹窗状态分析、金额口径冲突、框架设计或较复杂的失败定位时，切换到 GPT-5.6 Terra；不要把 Terra 或 Sol 作为所有任务的默认模型。
- 同一根因连续 3 次无进展，或诊断累计超过 20 分钟后，才允许启动一次 GPT-5.6 Sol/high 独立诊断；最多 2 次，仍无解就停止升级并请求用户协助。模型切换只影响分析和编写，不会加速 Playwright 页面本身的网络、接口或后台计算等待。
- 用户已授权：同一根因假设连续 3 次诊断无有效进展，或累计诊断超过 20 分钟后，可最多启动 2 次独立的 GPT-5.6 Sol / high 诊断任务。每次只分析当前阻塞问题；两次仍无解时停止升级并请求用户协助，不得再次自动升级或切换主任务模型。
- 已稳定的回归由本地 Playwright/pytest 命令直接运行。脚本执行本身不调用模型；只在失败日志、截图或 trace 需要分析时请求 AI，避免让 AI 逐条观察和等待常规回归。
- 将业务规则、变量和预期金额维护在 Excel、代码和共享 Skill 中；新场景使用简短任务描述并引用这些资产，避免在长对话中重复粘贴历史步骤、账号或截图。
- 页面探索先由测试人员确认一次正确业务路径；AI 后续负责固化、批量化和回归。需要截图时只提供关键异常截图，不为正常步骤逐页截图。
- 房间树选择优先使用组件提供的房间名称输入框进行过滤；输入后等待目标叶子节点真实出现，再勾选并确认。不要为速度直接按坐标点击未加载节点，也不要默认遍历整棵树。
- 云收费 UI 自动化以稳定性优先，不以最快完成为目标：关键页面、iframe、房间树、收费项树、日期下拉和金额计算必须等待真实可见/可用状态，允许保守等待和重试，不使用过快连续点击掩盖异步加载。
- 登录恢复约定：Standard1 若登录接口成功后页面提示“账号在其他地方登录”，不得直接判定登录失败；立即按当前环境和客户号再次提交登录，并重新请求 `#/Home?masterCustomerId=<客户号>`，再检查门户菜单和业务 iframe。该提示最多按一次瞬态提示处理；重登后仍无法进入业务页时才记录为登录阻塞并请求协助。
- 默认使用独立 Playwright 浏览器进行真实 DOM 控件定位、脚本调试和回归；稳定性验证优先使用有头模式，确认流程稳定后才切换无头模式批量回归。需要人工观察时仅展示浏览器窗口，不展示终端。内置浏览器只在测试人员需要协助演示复杂页面操作时使用，不作为常规定位链路。

## 开始前

1. 同时使用 `$cloud-billing-product-knowledge`，按任务读取其产品模型、领域规则、页面规则和安全边界。
2. 从仓库根目录工作。
3. 完整阅读 `references/verified-workflow.md`；其中只作为本项目实现、测试数据和已跑通脚本的记录，若与公共产品知识冲突，以用户最后确认的业务规则为准并同步修正。
4. 阅读 `src/pages/`、`src/config/settings.py`、`src/config/environments.py`、`tests/billing/test_create_periodic_bill.py`、`conftest.py` 和 `.env.<环境>.example` 中与场景相关的实现。
5. 用户的新步骤与旧用例冲突时，以用户最后确认且已在页面验证的步骤为准，并同步脚本与 Excel；若属于产品通用规则，同时更新公共 Skill。

## 实施工作流

### 1. 定义业务契约

先按“环境 → 客户 → 账号/角色 → 可访问项目 → 业务数据”确定归属，再整理前置条件、入口、逐步操作、测试数据、断言和清理方式。环境入口和本地凭据进入 `.env.<环境>`，客户、项目、房间、收费类型、收费项、账期、日期和原因等变量进入 `Settings`、`.env.<环境>.example` 与 Excel。Excel 的“账号/角色”列只填写稳定别名；真实账号、密码、令牌和登录状态不得写入代码、Excel 或 Skill。

### 2. 扩展 Page Object

- 页面定位和交互放在 `src/pages/`，测试文件只编排业务流程。
- 优先使用 role、label、稳定文本和限定容器；重复元素缩小到可见弹窗、目标 iframe 或唯一数据行。
- 复用 `BasePage.require_single` 或显式检查数量，避免 `.first` 掩盖错误页面。
- 同属账单中心的场景优先扩展 `BillingCenterPage`；职责明显不同才新建 Page Object。
- 关键操作后添加业务可见断言，不用固定等待代替状态判断。
- 收费标准名称全局不可重复。批量创建必须先精确查询并跳过已存在项，保存后再次精确查询；不得通过重试重复提交。
- 不同计费公式的动态参数必须进入结构化数据后再执行。未录制或缺少固定金额、阶梯、系数等参数时安全停止，禁止用统一默认值猜测创建。

### 3. 编写 pytest 场景

- 测试放入 `tests/<模块>/test_<场景>.py`。
- 创建、作废、删除等用例添加 `side_effect` 标记和默认关闭的安全开关。
- 账单中心直接创建成功后立即记录系统生成的唯一编号，清理必须用此编号精确定位。计费出账审核通过后则先跳转账单中心，按“账期 + 房间 + 未作废”筛选并唯一核对收费项和金额，再读取编号、作废、删除；两种入口不得混用清理方式。
- 运行时使用 `--test-env`、`--customer-id` 和 `--account-role` 明确环境、客户和账号；单账号用例也可使用 `@pytest.mark.customer("客户号")` 与 `@pytest.mark.account("role")`，跨角色或跨客户用例使用 `account_context(role, customer_id)` 创建独立 browser context。
- 用 `try/finally` 执行可选清理；只有对象已创建且双重清理开关开启时才能删除。计费出账用例若在生成、核对或审核阶段失败，必须在 `finally` 中先清理待处理卡片：待审核按“驳回（理由 `auto自动驳回`）→确认→删除”，待核对直接进入详情删除；清理失败写入 artifacts 但不得覆盖原始断言异常。计费出账已审核通过的账单仍按账单中心规则单独作废删除。
- 断言账期、计费期间、状态、编号以及最终不存在等业务结果。

### 4. 同步 Excel 用例

将最终步骤写入 `scripts/add_bill_demo_to_excel.py`，再运行脚本重建 `UI自动化回归测试用例模板_Demo.xlsx`。隐藏的“确定”“确认”和二次确认必须写成独立步骤。用例清单的“场景引用/覆盖项”单元格只维护 `SCENARIO_ID`，账号别名维护在该用例的“账号/角色”列；项目、房间、收费项、收费标准、减免和金额预期由 `SCENARIO_ID` 关联“收费场景配置”，账期、日期、通知选择和清理原因放入“运行参数”。禁止在多张表重复维护同一业务值，秘密数据不得进入 Excel。

Excel 必须作为执行代码的真实数据源：操作步骤中的 `${VARIABLE}` 应能在配置表标题中直接找到，代码按“用例编号 → SCENARIO_ID → 场景配置/运行参数”加载。创建、清理和永久删除授权只能从本地 `.env` 读取，Excel 中即使存在同名字段也不得生效。

涉及金额计算时，在“收费场景配置”工作表按“一行一个专用房间 + 收费项 + 收费标准组合”维护生效时间、计费公式、计算参数、减免配置和预期金额。模板、待补充和停用记录不得执行，只有已核验且启用的场景可被测试引用。

批量准备收费公式基准房间时，使用 `scripts/update_room_import_template.py` 同时生成 `房间导入模版.xlsx` 和 `房间收费标准映射表.xlsx`。导入模板只改“房间号”，按 `1001` 起连续短编号，其余字段复制模板首条数据；业务含义放在映射表中。计费公式保留系统原始名称；公式出现“计费面积”时，收费标准名称分别将其替换为建筑面积、使用面积、收费面积。每个周期类“公式 + 计费面积”必须分别建立按天、按满月两个标准并使用不同房间，名称追加 `-按天` 或 `-按满月`。跨收费类型存在同名公式时增加类型前缀。

### 5. 分级验证

先执行静态和无副作用验证：

```powershell
.\.venv\Scripts\python.exe -m compileall src tests
.\.venv\Scripts\python.exe -m pytest --collect-only -q --test-env standard1 --customer-id 93537
.\.venv\Scripts\python.exe scripts\add_bill_demo_to_excel.py
```

真实创建或清理只能在用户授权的测试环境中执行，并显式开启相应环境变量。执行后报告创建编号、断言、作废、删除以及失败截图或 trace。

## 安全边界

- 不因“运行测试”默认授权永久删除，沿用现有安全开关。
- 禁止仅凭账期、房间或当前唯一一行删除。账单中心直接创建使用本次账单编号精确匹配；计费出账审核通过后使用“账期 + 房间 + 未作废 + 收费项/金额”筛选出唯一行，再读取编号并作废、删除。
- 多行、编号不唯一、状态异常或确认文案变化时停止清理并报告。
- 系统行为与目标不一致时在提交前中止，例如显示 7 月却生成 8 月计费期间。
- 用户纠正步骤后，同步 Page Object、测试、Excel 和本 Skill 的验证参考。
- `prod` 环境禁止运行任何带 `side_effect` 标记的用例，也禁止开启创建、清理和永久删除开关；生产环境只允许显式设计的只读巡检。

## 完成标准

代码可收集、Excel 已重建、关键路径有断言、安全开关默认关闭且步骤与用户最终确认一致。未经授权未真实执行时，明确说明仅完成静态验证。

## 客户房间迁入前置自动化

- 客户导入模板 `前置数据模版文件/企业客户导入模板.xlsx` 是客户名称、所属项目和房屋路径的唯一数据源；脚本按客户名和完整房间路径精确校验，不按列表顺序猜测。
- 迁入流程使用 `scripts/migrate_customer_room.py --room <房间号>`；先选择客户管理1/客户管理A和项目，再按客户名称查询、编辑、打开“入驻楼栋房间”，只点击目标房间唯一操作行的“迁入”。
- 固定列表格可能渲染重复同步行，必须依据唯一客户结果、完整房间路径和“迁入/迁出”按钮判断；已显示“已入住”时幂等跳过，绝不点击“迁出”。
- 登录后的“通知提醒”和“全部公告”遮挡层必须先关闭，再进入客户管理；服务重启或懒加载时保持串行等待，不重复提交迁入。
## 场景与入口隔离

同一收费类型在不同 UI 入口必须使用独立场景 ID，不能仅复用一条场景：账单中心、计费出账（常规类/临时类入口）和临时台账的操作步骤、断言及清理动作分别维护。Excel 场景配置中的场景引用必须与用例的二级模块一一对应。

## 全量回归清理约束

当前回归用例清单中的 102 个场景均属于“生成账单后清理”的场景。凡场景实际创建出账单，无论入口（账单中心、计费出账常规类、计费出账临时类或临时台账）、账单类型（常规类或临时类）和收费项类型（周期、仪表、临时、押金等），都必须开启清理开关并完成对应的作废与删除流程；不能只验证生成成功后结束。账单中心入口按本次生成的账单编号清理，计费出账审核通过后回到账单中心按账期+房间+未作废条件读取编号清理，临时台账按其独立的作废说明和二次确认流程清理。报告必须分别记录创建断言、作废结果、删除结果和清理失败原因；生成失败或中途失败时，也必须在 finally 中清理已产生的待处理记录，避免遗留数据阻塞后续相同账期回归。执行前检查 `CLEANUP_CREATED_BILL=true` 与 `ALLOW_BILL_DELETION=true`，任一未开启都不得宣称清理完成。

当前项目正式回归矩阵必须保持为 102 个入口级场景：周期类 22 个房间分别覆盖账单中心和计费出账，共 44 条；仪表类 12 个房间分别覆盖账单中心和计费出账，共 24 条；临时类 11 个房间分别覆盖计费出账和临时台账，共 22 条；押金类 6 个房间分别覆盖计费出账和临时台账，共 12 条。账单中心合计 34 条、计费出账合计 51 条、临时台账合计 17 条。不同入口不得合并成一条用例，旧 Demo 用例不得混入正式批量采集；修改参数化绑定后必须通过 `pytest --collect-only` 校验总数和各入口数量。

清理实现不得在拿到本次账单编号后再用“精确账期”重新筛选来决定是否清理；不同页面版本可能只接受全年范围，二次筛选返回 0 会造成漏清理。编号一旦捕获，应直接按编号执行作废、删除和不存在复查；只有编号尚未捕获时，才使用已确认的账期+房间+收费项/金额组合定位，并将定位失败记录为清理失败。
## 页面变更后的回归用例同步

页面结构、控件定位或交互流程发生变更时，必须先完成脚本调整并在真实测试环境验证通过；验证通过后，立即将最终操作步骤、关键断言、参数引用和清理结果同步更新到 Excel 自动化回归测试用例文件（`UI自动化回归测试用例模板_Demo.xlsx`）对应场景行。仅更新受影响场景，保留 `SCENARIO_ID` 与配置表关联，不把账号、密码、Cookie 等敏感信息写入 Excel；更新后需重新读取并核对文件内容，确保脚本、Skill 与 Excel 三者一致。

该同步要求为跨资产规范：同一次页面或交互变更验证通过后，还必须同步更新 `cloud-billing-product-knowledge` 业务 Skill 和本 UI 自动化 Skill，确保业务规则、自动化实现与回归用例三者一致。
## 本地批量执行输出策略

本地批量回归时默认静默执行，将 pytest 标准输出、失败详情和截图/trace 写入 artifacts 日志；执行期间不持续向对话回显单条用例进度。任务结束后只读取汇总并更新测试结果、HTML/JUnit 报告和必要的失败摘要。若执行中出现阻塞或需要用户介入，再发送一次简短状态说明。
## Calculation-bill cleanup lookup

For bills generated through Billing Issuance, locate cleanup targets in Bill
Center by the exact billing month + room + charge item combination, require a
unique active (not voided) row, then void and delete it. Do not use a bill
number-only lookup for this entry point. Bill Center direct-create scenarios
may continue to clean up by the bill number captured from that creation.

Bills created from Billing Center and Billing Issuance (including regular and
temporary bill types) are cleaned in Bill Center.  Bills created directly from
Temporary Ledger (temporary and deposit types) exist only in Temporary Ledger
and must be cleaned there; do not redirect those records to Bill Center.

Before starting Billing Issuance cases, enforce a Bill Center room gate: scan
active bills for rooms 1001-1060 in the target billing month and void/delete
all matching records. Run the gate again after the Bill Center batch. Billing
Issuance must not start while any active bill remains for those rooms.

## Latest cleanup key rule

Bill Center and Temporary Ledger cleanup both search by billing month + room +
charge item. A captured bill number is report evidence only and must not be
entered as the cleanup filter. In Temporary Ledger Advanced Search, select the
charge item first, set both month boundaries to the target billing month, then
change bill object to “房间”. The redesigned room selector contains a readonly
mode control followed by the actual editable room input; enter the leaf room
there, expand the full asynchronous path, select the exact leaf and confirm
before submitting Search. After void/delete, repeat the same query and require
zero matching rows.

Entrypoint routing: Bill Center-created bills and all Billing Issuance-created
bills are located and voided/deleted in Bill Center. Temporary Ledger-created
bills are located and voided/deleted in Temporary Ledger. The fact that a
Billing Issuance temporary bill is also visible in Temporary Ledger does not
change its cleanup entrypoint.

## Batch entrypoint order

Full regression runs use one pytest session and one login, executing serially in
this order: all Bill Center scenarios, all Billing Issuance scenarios, then all
Temporary Ledger scenarios. After each entrypoint group, run pending-card,
temporary-bill, and Bill Center room-gate cleanup and verify no active records
remain before starting the next group. Keep per-test `finally` cleanup as well;
any group cleanup failure must fail the run and be reported.

## Temporary Ledger cleanup compatibility

- Do not click Advanced Search `重置` during consecutive cleanup. In the
  current UI it closes the drawer; overwrite charge item, both month fields,
  and room explicitly for every target.
- Commit both month inputs with Enter. Close a month picker with Escape only
  when `.el-picker-panel:visible` actually exists; an unconditional Escape can
  close Advanced Search.
- Charge-item options load asynchronously and may be outside the scroll
  viewport. Require one exact option across visible select dropdowns, scroll
  it into view, and click it.
- Element UI renders the bill-number row and the fixed-right action row as
  separate DOM tables. Map the main-row index to the fixed-right row before
  clicking `作废` or `删除`, and wait for the post-void row refresh before
  resolving `删除`.
- Accept both `确定作废` and `确认作废` confirmation labels. When a test has just
  created a bill, zero business-key matches is a cleanup failure, never an
  idempotent success.
- Session-end recovery must run after the final Temporary Ledger group as well
  as between entrypoint groups. It must not run for unit-only pytest sessions.
