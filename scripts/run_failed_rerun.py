"""重跑上一轮全量回归中的失败用例（同一 pytest 会话、串行、复用一次登录）。

设计约束（与本次重跑要求一致）：

* 只运行传入的失败 nodeid，不扩大到 module 级；同一 nodeid 的重复 Error
  记录只执行一次。
* 单个 pytest 会话完成全部用例，入口顺序固定为
  账单中心 → 计费出账 → 临时台账（由 conftest 排序约定保证）。
* 每条用例运行前按账期+房间+收费项只读预检，已有有效账单时记录并跳过。
* 只做逐用例 finally 业务键清理，不做整批房间的兜底扫尾
  （设置 SCOPED_BILLING_CLEANUP_ONLY，屏蔽批次级 cleanup 脚本）。
* 输出 console log + HTML 报告，不产出 JUnit 文件。
"""
from __future__ import annotations

import argparse
import atexit
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

GROUP_ORDER = {
    "test_create_periodic_center_bills.py": 0,
    "test_create_meter_bills.py": 0,
    "test_calculate_periodic_bill.py": 1,
    "test_calculate_temporary_bill.py": 1,
    "test_create_temporary_bill.py": 2,
    "test_create_deposit_bill.py": 2,
}


def _group_of(nodeid: str) -> int:
    filename = nodeid.split("::", 1)[0].rsplit("/", 1)[-1]
    if filename == "test_public_share_meter_billing.py":
        return 0 if "::test_bill_center_" in nodeid else 1
    return GROUP_ORDER.get(filename, 99)


def _load_nodeids(path: Path) -> list[str]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = raw.get("nodeids", [])
    unique = list(dict.fromkeys(str(item).strip() for item in raw if str(item).strip()))
    return sorted(unique, key=lambda node: (_group_of(node), unique.index(node)))


def _done_nodeids(progress_log: Path) -> set[str]:
    """Nodeids already reported in a progress log (passed/failed/skipped)."""
    done: set[str] = set()
    for line in progress_log.read_text(encoding="utf-8").splitlines():
        parts = line.split(" ", 2)
        if len(parts) == 3:
            done.add(parts[2].strip())
    return done


def _index_by_group(nodeids: list[str]) -> list[str]:
    return sorted(nodeids, key=lambda node: (_group_of(node), nodeids.index(node)))


def _summary(counts: dict[str, int], total: int) -> str:
    return (
        f"total={total} passed={counts.get('passed', 0)} "
        f"failed={counts.get('failed', 0)} skipped={counts.get('skipped', 0)} "
        f"error={counts.get('error', 0)}"
    )


class _Tee:
    """Mirror stdout to the console log so the run can be watched live."""

    def __init__(self, *streams) -> None:
        self._streams = streams

    def write(self, text: str) -> int:
        for stream in self._streams:
            stream.write(text)
            stream.flush()
        return len(text)

    def flush(self) -> None:
        for stream in self._streams:
            stream.flush()

    def isatty(self) -> bool:
        return False

    def fileno(self) -> int:
        return self._streams[0].fileno()


def main() -> int:
    parser = argparse.ArgumentParser(description="重跑上一轮失败用例")
    parser.add_argument(
        "--nodeids",
        type=Path,
        default=ROOT / "artifacts" / ".final4-failed-nodeids.json",
        help="失败 nodeid 清单 JSON（数组或含 nodeids 键的对象）",
    )
    parser.add_argument("--test-env", default="standard1")
    parser.add_argument("--customer-id", default="93537")
    parser.add_argument("--account-role", default="default")
    parser.add_argument("--label", default="failed-rerun")
    parser.add_argument(
        "--light",
        action="store_true",
        help="关闭录屏与 trace 采集，显著降低 CPU/磁盘占用（当前默认 addopts 会全程录制）",
    )
    parser.add_argument(
        "--resume-from",
        type=Path,
        default=None,
        help="已有 -progress.log：其中已出现结果的 nodeid 不再重复执行",
    )
    parser.add_argument(
        "--fixed-state",
        action="store_true",
        help="进度文件使用固定文件名，多次分段执行时累计（配合 --auto-resume 续跑）",
    )
    parser.add_argument(
        "--auto-resume",
        action="store_true",
        help="自动跳过固定进度文件中已出现结果的 nodeid",
    )
    parser.add_argument(
        "--max-cases",
        type=int,
        default=0,
        help="本次最多执行多少条（0 表示不限制），用于夜间分段执行",
    )
    args = parser.parse_args()

    nodeids = _load_nodeids(args.nodeids)
    full_total = len(nodeids)
    if args.resume_from and args.resume_from.exists():
        done = _done_nodeids(args.resume_from)
        before = len(nodeids)
        nodeids = [nodeid for nodeid in nodeids if nodeid not in done]
        print(
            f"[rerun] 断点续跑：已完成 {before - len(nodeids)} 条，剩余 {len(nodeids)} 条",
            flush=True,
        )
    if args.auto_resume:
        fixed_pending = ROOT / "artifacts" / f"{args.label}-progress.log"
        if fixed_pending.exists():
            done = _done_nodeids(fixed_pending)
            before = len(nodeids)
            nodeids = [nodeid for nodeid in nodeids if nodeid not in done]
            print(
                f"[rerun] 累计进度：已完成 {before - len(nodeids)} 条，"
                f"剩余 {len(nodeids)} 条待执行",
                flush=True,
            )
    if args.max_cases > 0:
        nodeids = nodeids[: args.max_cases]
        print(f"[rerun] 本次限量执行 {len(nodeids)} 条", flush=True)
    if not nodeids:
        print("[rerun] 全部用例均已执行完毕，无需再跑。", flush=True)
        return 0

    os.chdir(ROOT)
    from src.config.environments import load_test_environment

    load_test_environment(ROOT, args.test_env, override=True)
    os.environ["TEST_ENV"] = args.test_env
    os.environ["CUSTOMER_ID"] = args.customer_id
    os.environ["TEST_ACCOUNT_ROLE"] = args.account_role
    os.environ.pop("SCENARIO_ID", None)
    # 批次共享一次登录；禁用批次级兜底清理脚本。
    os.environ["QUICK_RELEASE_SHARED_LOGIN"] = "true"
    os.environ["SCOPED_BILLING_CLEANUP_ONLY"] = "true"

    from src.config.settings import settings

    if settings.test_environment == "prod":
        raise SystemExit("禁止在 prod 环境重跑带副作用的账单用例。")
    missing = [
        name
        for name, enabled in (
            ("ALLOW_BILL_CREATION", settings.allow_bill_creation),
            ("CLEANUP_CREATED_BILL", settings.cleanup_created_bill),
            ("ALLOW_BILL_DELETION", settings.allow_bill_deletion),
        )
        if not enabled
    ]
    if missing:
        raise SystemExit("账单创建/清理/删除安全开关未全部开启：" + ", ".join(missing))
    if settings.master_customer_id != args.customer_id:
        raise SystemExit(
            f"本地配置客户号 {settings.master_customer_id} 与请求 {args.customer_id} 不一致。"
        )

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    artifacts = ROOT / "artifacts"
    artifacts.mkdir(exist_ok=True)

    # 单实例保护：夜间分段执行时，若上一批仍在跑，本轮直接退出。
    # 两个 pytest 并发会互相拖慢，导致房间树懒加载超时、成片假失败。
    lock = artifacts / f"{args.label}.lock"
    if lock.exists() and (time.time() - lock.stat().st_mtime) < 90 * 60:
        print(
            f"[rerun] 检测到已有批次正在运行（{lock.name}，"
            f"{int((time.time() - lock.stat().st_mtime) / 60)} 分钟前更新），本轮跳过。",
            flush=True,
        )
        return 0
    lock.write_text(
        f"pid={os.getpid()} started={timestamp}\n", encoding="utf-8"
    )
    atexit.register(lock.unlink, missing_ok=True)
    html_report = artifacts / f"{args.label}-{timestamp}.html"
    console_log = artifacts / f"{args.label}-{timestamp}.log"
    if args.fixed_state:
        # 固定文件名：夜间多次分段执行时进度累计到同一份日志。
        progress_log = artifacts / f"{args.label}-progress.log"
        progress_state = artifacts / f"{args.label}-progress.json"
        manifest = artifacts / f"{args.label}-manifest.json"
    else:
        progress_log = artifacts / f"{args.label}-{timestamp}-progress.log"
        progress_state = artifacts / f"{args.label}-{timestamp}-progress.json"
        manifest = artifacts / f"{args.label}-{timestamp}-nodeids.json"
    manifest.write_text(
        json.dumps(
            {
                "source": str(args.nodeids),
                "environment": settings.test_environment,
                "customer_id": settings.master_customer_id,
                "account_role": args.account_role,
                "count": len(nodeids),
                "nodeids": nodeids,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    common = [
        "--test-env", settings.test_environment,
        "--customer-id", settings.master_customer_id,
        "--account-role", args.account_role,
    ]
    env = os.environ.copy()
    env["TEST_PROGRESS_LOG"] = str(progress_log)
    env["TEST_PROGRESS_STATE"] = str(progress_state)
    # In-process pytest.main reads os.environ, not the subprocess env copy.
    os.environ["TEST_PROGRESS_LOG"] = str(progress_log)
    os.environ["TEST_PROGRESS_STATE"] = str(progress_state)

    print(f"[rerun] 目标 {len(nodeids)} 条失败用例；环境={settings.test_environment} "
          f"客户={settings.master_customer_id} 账号={args.account_role}", flush=True)
    print("[rerun] 安全开关: 创建/清理/删除 = 已开启；批次兜底扫尾 = 已禁用", flush=True)

    collect = subprocess.run(
        [sys.executable, "-m", "pytest", *nodeids, "--collect-only", "-q", *common],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    collected = [
        line.strip()
        for line in collect.stdout.splitlines()
        if line.strip().startswith("tests/") and "::" in line
    ]
    if collect.returncode or len(collected) != len(nodeids):
        print(collect.stdout[-4000:], flush=True)
        print(collect.stderr[-2000:], flush=True)
        raise SystemExit(
            "失败用例未能全部收集，未启动任何业务写操作："
            f"collect_exit={collect.returncode} collected={len(collected)} "
            f"expected={len(nodeids)}"
        )
    print(f"[rerun] collect-only 通过：{len(collected)}/{len(nodeids)} 条可收集", flush=True)

    with console_log.open("w", encoding="utf-8") as log:
        log.write(f"[rerun] {datetime.now().isoformat(timespec='seconds')}\n")
        log.write(
            f"[rerun] targets={len(nodeids)} env={settings.test_environment} "
            f"customer={settings.master_customer_id} role={args.account_role}\n"
        )
        log.flush()

        import pytest

        light_args = ["--video", "off", "--tracing", "off"] if args.light else []
        original_stdout, original_stderr = sys.stdout, sys.stderr
        sys.stdout = _Tee(original_stdout, log)
        sys.stderr = _Tee(original_stderr, log)
        try:
            code = pytest.main(
                [
                    *nodeids,
                    *common,
                    "-v",
                    "-p", "no:cacheprovider",
                    *light_args,
                    f"--html={html_report}",
                    "--self-contained-html",
                ],
                plugins=[],
            )
        finally:
            sys.stdout, sys.stderr = original_stdout, original_stderr

    counts = {"passed": 0, "failed": 0, "skipped": 0, "error": 0}
    if progress_log.exists():
        for line in progress_log.read_text(encoding="utf-8").splitlines():
            parts = line.split(" ", 2)
            if len(parts) < 3:
                continue
            outcome = parts[1].strip().lower()
            if outcome in counts:
                counts[outcome] += 1
            elif outcome in {"error", "failed"}:
                counts[outcome] += 1

    summary = {
        "run_at": timestamp,
        "targets": len(nodeids),
        "full_total": full_total,
        "completed_total": sum(counts.values()),
        "remaining_total": max(full_total - sum(counts.values()), 0),
        "exit_code": int(code),
        "counts": counts,
        "html_report": html_report.as_posix(),
        "console_log": console_log.as_posix(),
        "progress_log": progress_log.as_posix(),
    }
    (artifacts / f"{args.label}-{timestamp}-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # 便于次日直接查看的纯文本摘要（不写凭据）。
    text_lines = [
        f"运行批次：{args.label}",
        f"本次开始时间：{timestamp}",
        f"环境：{settings.test_environment}  客户：{settings.master_customer_id}  账号：{args.account_role}",
        f"本次执行条数：{len(nodeids)}  清单总条数：{full_total}",
        f"累计结果：通过 {counts.get('passed', 0)} / 失败 {counts.get('failed', 0)} "
        f"/ 跳过 {counts.get('skipped', 0)} / 错误 {counts.get('error', 0)}",
        f"累计已完成 {sum(counts.values())} 条，剩余 {max(full_total - sum(counts.values()), 0)} 条",
        f"pytest 退出码：{int(code)}",
        f"HTML 报告：{html_report.as_posix()}",
        f"console log：{console_log.as_posix()}",
        f"逐条结果：{progress_log.as_posix()}",
    ]
    if progress_log.exists():
        failed = [
            line.split(" ", 2)[2].strip()
            for line in progress_log.read_text(encoding="utf-8").splitlines()
            if len(line.split(" ", 2)) == 3 and line.split(" ", 2)[1] == "FAILED"
        ]
        skipped = [
            line.split(" ", 2)[2].strip()
            for line in progress_log.read_text(encoding="utf-8").splitlines()
            if len(line.split(" ", 2)) == 3 and line.split(" ", 2)[1] == "SKIPPED"
        ]
        if failed:
            text_lines.append("")
            text_lines.append("失败用例：")
            text_lines.extend(f"  - {item}" for item in failed)
        if skipped:
            text_lines.append("")
            text_lines.append("跳过用例（运行前已存在有效账单）：")
            text_lines.extend(f"  - {item}" for item in skipped)
    summary_text = "\n".join(text_lines) + "\n"
    (artifacts / f"{args.label}-{timestamp}-summary.txt").write_text(
        summary_text, encoding="utf-8"
    )
    (artifacts / f"{args.label}-LATEST.txt").write_text(summary_text, encoding="utf-8")
    print(
        f"[rerun] 完成 exit={int(code)} {_summary(counts, len(nodeids))}",
        flush=True,
    )
    print(f"[rerun] HTML 报告: {html_report.as_posix()}", flush=True)
    print(f"[rerun] console log: {console_log.as_posix()}", flush=True)
    return 0 if int(code) in (0, 1) else int(code)


if __name__ == "__main__":
    raise SystemExit(main())
