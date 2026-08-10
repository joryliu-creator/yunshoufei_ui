---
name: billing-center-ui-automation
description: 为天启标准云收费 Web 应用设计、生成、调整和验证 Python Playwright UI 自动化脚本及 Excel 回归用例。用于账单中心及相邻业务场景，尤其适合在本项目现有 Page Object、pytest、登录状态复用、Element UI 弹窗/树/iframe 处理、安全作废删除和测试数据参数化基础上新增场景，或把人工操作步骤同步为可执行脚本与用例。
---

# 账单中心 UI 自动化

## 目标

基于本仓库已经真实跑通的 Demo 新增回归场景。保持 Python + Playwright 同步 API + pytest + Page Object 结构，并让脚本、Excel 用例和最终人工确认步骤一致。

## 开始前

1. 从仓库根目录工作。
2. 完整阅读 `references/verified-workflow.md`。
3. 阅读 `src/pages/`、`src/config/settings.py`、`src/config/environments.py`、`tests/billing/test_create_periodic_bill.py`、`conftest.py` 和 `.env.<环境>.example` 中与场景相关的实现。
4. 用户的新步骤与旧用例冲突时，以用户最后确认且已在页面验证的步骤为准，并同步脚本与 Excel。

## 实施工作流

### 1. 定义业务契约

先按“环境 → 客户 → 账号/角色 → 可访问项目 → 业务数据”确定归属，再整理前置条件、入口、逐步操作、测试数据、断言和清理方式。环境入口和本地凭据进入 `.env.<环境>`，客户、项目、房间、收费类型、收费项、账期、日期和原因等变量进入 `Settings`、`.env.<环境>.example` 与 Excel。Excel 的“账号/角色”列只填写稳定别名；真实账号、密码、令牌和登录状态不得写入代码、Excel 或 Skill。

### 2. 扩展 Page Object

- 页面定位和交互放在 `src/pages/`，测试文件只编排业务流程。
- 优先使用 role、label、稳定文本和限定容器；重复元素缩小到可见弹窗、目标 iframe 或唯一数据行。
- 复用 `BasePage.require_single` 或显式检查数量，避免 `.first` 掩盖错误页面。
- 同属账单中心的场景优先扩展 `BillingCenterPage`；职责明显不同才新建 Page Object。
- 关键操作后添加业务可见断言，不用固定等待代替状态判断。

### 3. 编写 pytest 场景

- 测试放入 `tests/<模块>/test_<场景>.py`。
- 创建、作废、删除等用例添加 `side_effect` 标记和默认关闭的安全开关。
- 创建成功后立即记录系统生成的唯一编号，清理必须用此编号精确定位。
- 运行时使用 `--test-env`、`--customer-id` 和 `--account-role` 明确环境、客户和账号；单账号用例也可使用 `@pytest.mark.customer("客户号")` 与 `@pytest.mark.account("role")`，跨角色或跨客户用例使用 `account_context(role, customer_id)` 创建独立 browser context。
- 用 `try/finally` 执行可选清理；只有对象已创建且双重清理开关开启时才能删除。
- 断言账期、计费期间、状态、编号以及最终不存在等业务结果。

### 4. 同步 Excel 用例

将最终步骤写入 `scripts/add_bill_demo_to_excel.py`，再运行脚本重建 `UI自动化回归测试用例模板_Demo.xlsx`。隐藏的“确定”“确认”和二次确认必须写成独立步骤。操作步骤使用 `${VARIABLE_NAME}` 占位符，同一用例行的“测试数据”单元格使用 `VARIABLE_NAME=实际值`；复制相同流程的新用例时只修改测试数据。可复用数据也可以同步到“测试数据”工作表，秘密数据不得进入 Excel。

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
- 禁止仅凭账期、房间或当前唯一一行删除。先筛选缩小范围，再用本次记录的账单编号精确匹配。
- 多行、编号不唯一、状态异常或确认文案变化时停止清理并报告。
- 系统行为与目标不一致时在提交前中止，例如显示 7 月却生成 8 月计费期间。
- 用户纠正步骤后，同步 Page Object、测试、Excel 和本 Skill 的验证参考。
- `prod` 环境禁止运行任何带 `side_effect` 标记的用例，也禁止开启创建、清理和永久删除开关；生产环境只允许显式设计的只读巡检。

## 完成标准

代码可收集、Excel 已重建、关键路径有断言、安全开关默认关闭且步骤与用户最终确认一致。未经授权未真实执行时，明确说明仅完成静态验证。
