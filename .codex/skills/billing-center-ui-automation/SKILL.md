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
- When the portal displays `账号在其他地方登录` during any automated login,
  treat it as a recoverable session conflict: clear the current stale session,
  perform one fresh login with the configured credentials, reopen the explicit
  customer Home route, and verify the portal menu plus target business iframe.
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
- 同一根因连续 3 次无进展、单一问题持续超过 20 分钟，或出现会话/iframe/弹窗/清理等多状态耦合时，启动一次独立 GPT-6 Sol 轻量级子 agent 诊断；该任务聚焦根因和最小修复，不重复跑批次。
- 主任务模型不自动切换；该升级指独立子 agent 使用 GPT-6 Sol、low reasoning effort。模型不会加速 Playwright 页面本身的网络或后台等待。
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
- 账单中心直接创建、以及计费出账审核通过后进入账单中心清理的账单，统一按“账期 + 房间 + 收费项”定位；必须确认唯一命中本次有效账单，再核对金额和状态。账单编号仅作为报告证据或查询结果中的行身份核对，不得作为筛选条件。
- 账单中心清理顺序固定为：勾选目标行 → “更多/批量作废” → 填写作废原因并确认 → 重新按相同业务键定位已作废目标 → “更多/批量删除”并确认 → 用相同业务键复查为 0 条。若业务键返回多条且无法唯一确认本次账单，停止清理并报告，不得扩大范围或按编号筛选。
- 新版账单中心高级搜索中，“收费对象”决定账单归属主体；房间账单先切换为“收费对象-房间”，再在相邻房间树中选择完整路径并确认。“关联对象”是当前收费对象关联的资产，可作为额外条件按需选择；按房间清理时留空，不可用它替代房间筛选。账单清理仍需同时设置账期、房间和收费项。
- 账单中心按账期+房间+收费项查询时，先设置“收费对象-房间”并确认目标房间，再设账期、收费项，最后核对三条件仍同时保留后搜索。收费项和账期先变更再打开房间树时，树可能不加载；不得因此退化为只按房间查询。临时台账继续遵循其单独验证的筛选顺序。
- 工作台“业务办理收费台”房间档案新增账单使用独立 Page Object：按房间搜索并等待唯一路径，打开档案并核对客户、收费项及收费标准；点击“新增账单”后只核验抽屉默认选中的房间及收费对象，不重复选择房间。新增收费项后，编辑明细设置最晚缴款日并保存，再提交账单。
- 工作台创建前仍须在账单中心按完整业务键做只读预检；创建后以成功数、账期、应收日期和独立计算金额核验，再在账单中心按同一业务键清理。账单中心清理必须先批量作废（含原因）再批量删除，最后复查为 0 条；任一阶段结果不唯一时停止而不扩大范围。
- 运行时使用 `--test-env`、`--customer-id` 和 `--account-role` 明确环境、客户和账号；单账号用例也可使用 `@pytest.mark.customer("客户号")` 与 `@pytest.mark.account("role")`，跨角色或跨客户用例使用 `account_context(role, customer_id)` 创建独立 browser context。
- 用 `try/finally` 执行可选清理；只有对象已创建且双重清理开关开启时才能删除。计费出账用例若在生成、核对或审核阶段失败，必须在 `finally` 中先清理待处理卡片：待审核按“驳回（理由 `auto自动驳回`）→确认→删除”，待核对直接进入详情删除；清理失败写入 artifacts 但不得覆盖原始断言异常。计费出账已审核通过的账单仍按账单中心规则单独作废删除。
- 断言账期、计费期间、状态、编号以及最终不存在等业务结果。

### 4. 同步 Excel 用例

将最终步骤写入 `scripts/add_bill_demo_to_excel.py`，再运行脚本重建 `UI自动化回归测试用例模板_Demo.xlsx`。隐藏的“确定”“确认”和二次确认必须写成独立步骤。用例清单的“场景引用/覆盖项”单元格只维护 `SCENARIO_ID`，账号别名维护在该用例的“账号/角色”列；项目、房间、收费项、收费标准、减免和金额预期由 `SCENARIO_ID` 关联“收费场景配置”，账期、日期、通知选择和清理原因放入“运行参数”。禁止在多张表重复维护同一业务值，秘密数据不得进入 Excel。

Excel 必须作为执行代码的真实数据源：操作步骤中的 `${VARIABLE}` 应能在配置表标题中直接找到，代码按“用例编号 → SCENARIO_ID → 场景配置/运行参数”加载。创建、清理和永久删除授权只能从本地 `.env` 读取，Excel 中即使存在同名字段也不得生效。

涉及金额计算时，在“收费场景配置”工作表按“一行一个专用房间 + 收费项 + 收费标准组合”维护生效时间、计费公式、计算参数、减免配置和预期金额。模板、待补充和停用记录不得执行，只有已核验且启用的场景可被测试引用。

绑定房间收费设置的周期类收费标准，预期金额按标准自身的不足月方式计算：按满月时，不足月仍收整月月单价；按天时，使用 `月单价 ÷ 当月自然日数 × 本期计费天数`。例如 3 月 7 日至 3 月 31 日若按首尾包含计为 25 天，按天金额为 `月单价 ÷ 31 × 25`。用例配置必须保存标准类型、计费期间、计费天数和独立计算的预期金额；计费天数以已验证的产品/页面口径为准。此规则仅适用于周期类收费标准，不应用于仪表公摊方案自身的不足月分配，后者按独立公摊业务规则计算。

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
- 禁止仅凭账期、房间、收费项中的部分条件或“当前恰好只有一行”删除。账单中心直接创建和计费出账审核通过后的账单均使用“账期 + 房间 + 收费项”定位唯一有效行；金额、状态和账单编号用于核验目标身份，账单编号不得输入筛选框。账单中心必须批量作废（含作废原因）后批量删除。
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

所有实际创建账单的场景都必须按入口完成清理，不能只验证生成成功后结束。账单中心直接创建和计费出账审核通过后进入账单中心的账单，均按“账期 + 房间 + 收费项”定位；账单中心先批量作废（填写作废原因），再批量删除，并用相同业务键复查为 0 条。临时台账自身产生的记录也按“账期 + 房间 + 收费项”定位，但清理动作保持独立：行内作废后点击行内“删除”并确认。待处理计费出账卡片仍按其状态流转规则清理。报告分别记录创建断言、作废结果、删除结果和清理失败原因；中途失败时在 `finally` 中回收本次已产生的数据。执行前检查 `CLEANUP_CREATED_BILL=true` 与 `ALLOW_BILL_DELETION=true`，任一未开启都不得宣称清理完成。

当前项目正式回归矩阵必须保持为 102 个入口级场景：周期类 22 个房间分别覆盖账单中心和计费出账，共 44 条；仪表类 12 个房间分别覆盖账单中心和计费出账，共 24 条；临时类 11 个房间分别覆盖计费出账和临时台账，共 22 条；押金类 6 个房间分别覆盖计费出账和临时台账，共 12 条。账单中心合计 34 条、计费出账合计 51 条、临时台账合计 17 条。不同入口不得合并成一条用例，旧 Demo 用例不得混入正式批量采集；修改参数化绑定后必须通过 `pytest --collect-only` 校验总数和各入口数量。

公摊账单专项作为核心 102 条之外的可执行扩展矩阵维护，不得误删或折算进上述核心数量：周期类公摊 10 个关联房间分别覆盖账单中心和计费出账，共 20 条；正式水表/电表公摊 32 个关联房间分别覆盖两个入口，共 64 条。两入口分别使用独立 `YSF-BILL-*` / `YSF-CALC-*` 用例编号和 `SCENARIO_ID`，由默认 `tests/billing` 批次发现并串行执行；公共仪表及公摊基线不在账单清理范围内，账单仍须按入口规则逐条清理。

账单编号被捕获后也不得用于筛选框。清理目标发现、作废后重选以及最终复查均使用同一“账期 + 房间 + 收费项”业务键；可在查询结果中核对账单编号以区分目标行，但不得用编号替代业务键。如果页面无法按完整业务键查询，或结果不唯一且无法确认本次记录，停止并报告，不能改用编号筛选或扩大查询后盲目操作。
## 页面变更后的回归用例同步

页面结构、控件定位或交互流程发生变更时，必须先完成脚本调整并在真实测试环境验证通过；验证通过后，立即将最终操作步骤、关键断言、参数引用和清理结果同步更新到 Excel 自动化回归测试用例文件（`UI自动化回归测试用例模板_Demo.xlsx`）对应场景行。仅更新受影响场景，保留 `SCENARIO_ID` 与配置表关联，不把账号、密码、Cookie 等敏感信息写入 Excel；更新后需重新读取并核对文件内容，确保脚本、Skill 与 Excel 三者一致。

该同步要求为跨资产规范：同一次页面或交互变更验证通过后，还必须同步更新 `cloud-billing-product-knowledge` 业务 Skill 和本 UI 自动化 Skill，确保业务规则、自动化实现与回归用例三者一致。
## 本地批量执行输出策略

本地批量回归时默认静默执行，将 pytest 标准输出、失败详情和截图/trace 写入 artifacts 日志；同时维护一个很小的进度状态文件（完成数、通过/失败数、最后用例、最后更新时间）。执行期间每 60--120 秒只读取该摘要，不读取完整日志、不逐条回显；任务结束后才读取汇总和失败详情并更新报告。若最后更新时间超过阈值且完成数不变，才按模型路由规则启动诊断。

## 收费标准专项清理

- 收费标准创建、查询和删除均在“云收费 → 收费设置 → 收费标准管理”完成。
- 抽成类收费标准暂不纳入当前批量专项回归；待单独录制适用项目与收费项异步刷新流程后再启用，现有参数化脚本会显式跳过该类。
- 新环境业务初始化使用 `scripts/create_charge_standards.py` 的默认业务名称模式，直接创建房间映射表所需的非 `AT-` 收费标准；自动化专项必须显式使用 `--automation-names`，不得用 `AT-` 测试标准替代业务初始化数据。
- 收费标准新建先选收费类型和适用项目，再等待收费项选择框在异步刷新后重新可见、可用，最后精确选择收费项并确认选中值稳定；不可依赖即时 `count()` 或先选收费项再切换项目。
- Element UI 可能同时保留项目、收费项和计费公式的下拉弹层；选择时必须绑定包含目标选项的当前弹层，禁止使用全局第一个可见下拉层。
- 自动化仅清理本次运行创建且以 `AT-` 开头的收费标准。删除前若状态为“启用”，必须先切换为“未启用”（兼容页面文案“停用”），确认状态变化后再删除，并按完整名称复查不存在。
## Calculation-bill cleanup lookup

For bills generated through Billing Issuance and for bills created directly in
Bill Center, locate cleanup targets by the exact billing month + room + charge
item combination and require a unique active row. The captured bill number is
evidence/row identity only, never a search filter. In Bill Center, select the
row, use More / Batch Void with a required reason, then More / Batch Delete;
repeat the same business-key query and require zero results. If the key is
ambiguous, stop and report instead of filtering by bill number.

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

## Verified bill-discount workflow

- Reuse the established `BillingCenterPage` create-bill flow. When several
  business iframes remain mounted, retain the Playwright `Frame` that contains
  the Bill Center controls; do not rebuild a `FrameLocator` from its name.
- If the portal already has a Bill Center or 减免管理-新 top tab, click that
  tab to switch the mounted iframe. Use the left menu only when the tab does
  not exist, and still assert the target iframe's business controls afterward.
- In 选择减免账单, filter only by room, then select the matching bill. Do
  not add billing-month or charge-item criteria to that screen. Discount
  Management Advanced Search also selects the room directly and must not use
  Temporary Ledger's bill-object hover menu.
- The create drawer's room field uses the `jie-content` input whose placeholder
  is 请选择. Advanced Search uses `jie-dialog-label` / `jie-poper-input`,
  while its visible tree popover is mounted at the discount iframe root.
- Debug-only continuation may explicitly enable
  `REUSE_EXISTING_DISCOUNT_BILL=true` and
  `DEFER_DISCOUNT_BILL_CLEANUP_ON_FAILURE=true`. Formal regression leaves both
  unset and preserves `finally` cleanup. Even debug runs must void/delete and
  recheck the bill after the whole flow passes.
- Real verification on 2026-09-09 passed for room 1101 and billing month
  2026-08: original 10.00, discount 5.00, receivable 5.00; application, audit,
  amount assertions, void, delete, and absence recheck all passed.
- Discount regression currently includes 1101 (按折扣), 1102 (按固定金额),
  and 1103 (自定义金额). 1102 reuses the verified 1101 interaction sequence.
  For 1103, after choosing the scheme, fill 5 in the editable input to the
  right of 减免金额, trigger blur/change (for example with Tab), and verify
  the value remains 5 before continuing. 1104-1106 are excluded until penalty
  data exists. Room 1103 passed create, application, audit, amount assertion,
  void, delete, and absence recheck on 2026-09-09.

## Model routing for debugging

Use model capacity according to the work, so repeated low-quality diagnosis does
not cost more than one focused escalation:

- Use GPT-5.6 Luna for running an already-stable regression, mechanical edits,
  Excel or documentation maintenance, log summarization, and simple locator
  corrections whose root cause is already known.
 - Use GPT-5.6 Terra as the default diagnostic tier for ordinary Playwright
  failures, including iframe readiness, Element UI overlays, asynchronous
  dropdowns, locator ambiguity, and page-state recovery.
- When the same root-cause hypothesis has made no material progress after
  three attempts, diagnosis has exceeded 20 minutes, or the failure crosses
  several coupled states such as login, mounted iframes, business submission,
  and cleanup, launch one bounded independent GPT-6 Sol/light diagnosis and
  repair (reasoning low, normal execution speed). Do not continue Luna retries
  after this threshold. This is the user's explicit escalation rule for this
  project.
- Use GPT-6 Sol only for that bounded escalation, or when the user explicitly
  authorizes it; do not repeatedly launch Sol for unchanged evidence.
- A model escalation is for diagnosis and the smallest justified fix. Stable
  script execution remains local and does not require a reasoning model to
  watch each test or stream logs.
 - Codex cannot silently replace the model of the currently running main task.
   The user changes that model in the Codex UI. When collaboration tools and the
   current task policy permit model overrides, Codex may launch one independent
   GPT-6 Sol/light diagnostic task after the threshold, then apply and verify
   its evidence in the main task. If unavailable, report the limitation; do not
   claim the main-task model changed.
- Record the root cause, evidence, changed code, and verification result after
  an escalation. A second GPT-6 Sol diagnosis is allowed only for new evidence
  or a genuinely different hypothesis. If it remains inconclusive, report the
  evidence and request focused user assistance rather than repeatedly
  escalating on unchanged evidence.

## 周期类公摊方案专项

- 周期类公摊方案按“一条参数化用例对应一种公摊方式/计费面积组合”维护，入口为
  `云收费 -> 收费设置 -> 公摊方案`；创建前必须选择项目、收费项类型“周期性费用”、
  公摊周期性收费项和对应收费标准。
- 三种周期公摊方式分别覆盖按房间设置比例分摊、按房间设置金额分摊、按住户面积及所在楼层
  对应系数公摊。比例/金额场景必须使用两个房间并校验结构化参数；面积场景分别覆盖建筑面积、
  使用面积、收费面积，阶梯上下限必须满足当前后端“连续且非空”的校验。
- 依赖下拉必须在上一级选项真正落值且目标选项唯一可见后再选择；收费项下拉为空时只允许
  有界地重建一次抽屉组件并重试，不得无限点击或把空列表当成通过。
- 正式参数化回归在同一个已认证 BrowserContext 内复用登录，但每个公摊场景使用新 Page，避免
  上一个 iframe/抽屉的 Vue 状态污染；场景结束在 `finally` 关闭抽屉。副作用开关
  `ALLOW_PUBLIC_SHARE_SCHEME_CREATION` 默认关闭，只有明确实跑时显式开启。
- 公摊参与房间默认不绑定收费项；但“收费面积”由后端已有房间收费配置提供。若公摊专用房间
  返回收费面积 0，禁止通过脚本伪造禁用输入框，必须改用已配置收费面积的基准房间或先补齐
  明确的前置数据，并在 Excel 专项记录中说明原因。
- 创建成功后按方案名称精确查询并校验收费项类型、关联收费项、公摊方式和计费面积；本专项
  仅验证创建，不自动删除业务方案，除非另有明确的清理授权。
- 周期类公摊方案的自动化名称必须以 `AT-` 开头，并在名称末尾追加该方案关联的完整房间对，
  例如 `...-1201-1202`；用例参数、Excel 和清理名单必须使用同一完整名称。
- 依赖计费面积的公摊房间对必须有可区分的基础面积：同一房间的建筑面积与使用面积不能相等，
  且同一方案的两个参与房间不能使用完全相同的面积组合。`scripts/add_public_share_rooms.py`
  维护周期类和仪表类计费面积公摊的专用房间对及备注。

## 仪表类公摊方案专项

- 水表、电表、燃气表、空调使用同一个“新增公摊方案”页面流程和 Page Object；按数据参数切换
  仪表类型、公共仪表、关联收费项/收费标准及房间对，不得为每种仪表复制一套交互步骤。
- 每种仪表按户、按计费面积、按住户所在楼层系数、按住户计费面积系数四种方式分别覆盖
  按满月计费和按天计费；每个方案绑定两个房间，场景数据由 `公摊方案专项` Excel 工作表驱动。
- 仪表公摊方案的按天/按满月必须按公摊业务规则独立计算，不能复用或改写关联收费标准自身的按天/按满月规则。用量周期取相邻抄表时间（例如 2026-08 为
  `2026-07-04 00:00:00` 至 `2026-08-04 00:00:00`）；入住日按首尾包含计数，例如 2026-07-15 至 2026-08-04 为 21 天。
  两房均不足周期时按各自实际入住天数分摊、剩余由物业承担；两房均覆盖完整周期时按满周期公式分摊；仅一房不足周期时先算该房份额，仪表剩余用量全部分配给另一满周期房间。完整周期天数的分母口径未确认前，不得硬编码比例或预期金额；收费标准原有算法保持不变。
- 水表、电表初始化方案作为非 `AT-` 环境基线创建并保留；燃气表、空调专项回归使用 `AT-`
  名称，按独立清理阶段的完整名称精确删除。不得把初始化基线加入回归清理名单。
- 按住户计费面积系数方式的阶梯面积上下限必须满足当前后端连续且非空校验；创建后必须
  按名称回查并核对仪表类型、公共仪表、收费项/标准、公摊方式和两个参与房间。
- `scripts/create_initial_instrument_public_share_schemes.py` 仅负责水表/电表正式基线初始化；
  `scripts/run_instrument_public_share_regression.py --allow-create --allow-cleanup` 负责燃气/空调
  AT 专项串行创建及精确清理。两者均需显式授权开关。

### 测试数据清理边界

- 新环境初始化使用 `scripts/create_initial_public_share_schemes.py`，正式方案不带 `AT-` 前缀，
  只创建/校验并长期保留；不得把初始化脚本接入回归清理。
- 初始化脚本创建的正式业务方案不参与自动清理；只有本次回归创建且名称带 `AT-` 前缀的方案允许删除。
- 创建与清理分离为两个显式开关：创建使用 `ALLOW_PUBLIC_SHARE_SCHEME_CREATION`，清理同时要求 `CLEANUP_PUBLIC_SHARE_SCHEMES` 与 `ALLOW_PUBLIC_SHARE_SCHEME_DELETION`。
- 清理必须按自动化记录的精确方案名称逐条执行并复查列表归零，禁止按模糊关键字、行号或全量删除。
- 清理失败必须使测试失败，不得把残留数据报告为通过；清理完成后才允许进入后续依赖公摊方案的场景。

## Serial regression compatibility rules (latest project addendum)

These rules capture the failures found during the 2026-09-21 periodic
public-share calculation regression and take precedence over weaker, older
locator assumptions:

- Activate the target business tab before inspecting or closing any mounted
  iframe/drawer. If a previous calculation detail remains visible, or the
  calculation home shows more than the two normal `开始计算` actions, reload
  the authenticated customer Home once and reopen the target tab. Never carry
  a stale drawer into the next parameterized case.
- Treat the calculation flow as a state machine: home -> configuration drawer
  -> rule detail -> pending card -> reconciliation -> audit -> Bill Center
  cleanup. Each transition must wait for a real visible business state; a
  fixed sleep or a generic iframe index is not a state assertion.
- The backend may return a transient `创建失败` toast. Detect failure toasts
  before the success wait, save a compact diagnostic artifact, and retry the
  same configured action at most once. If the retry fails, stop the case and
  preserve the original error; do not loop indefinitely or treat it as passed.
- Element UI may display overlapping success/error toasts. Do not assert
  uniqueness over the whole visible toast collection; poll the collection and
  accept the expected business message when any visible toast matches it.
- Every parameterized case must reset page state and execute pending-card
  cleanup in `finally`, including failures before final submission. A batch
  may enter the next case only after the current case's page state is clean.
- A batch is stable only when it passes the selected cases from a fresh login,
  leaves zero pending cards and zero business-key-matched residual bills, and
  no manual intervention is needed. A single successful rerun after a first
  failure is evidence of recovery, not proof of compatibility.
