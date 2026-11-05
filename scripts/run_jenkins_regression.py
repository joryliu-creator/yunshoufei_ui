"""Run the cloud-billing UI regression suite from Jenkins.

The runner is intentionally thin: pytest remains the source of test
selection and cleanup, while this script supplies a repeatable CI entry point
and always produces a JUnit XML file plus the HTML regression report.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_JUNIT = ROOT / "artifacts" / "jenkins-junit.xml"
DEFAULT_HTML = ROOT / "artifacts" / "jenkins-regression-report.html"


def _read_env_file(environment: str) -> dict[str, str]:
    """Read only simple KEY=value entries for CI preflight checks.

    pytest loads the selected dotenv file itself.  This small reader avoids
    making the runner depend on shell-specific dotenv behavior and never
    prints credentials.
    """
    candidates = [ROOT / f".env.{environment}"]
    if environment == "standard1":
        candidates.append(ROOT / ".env")
    values: dict[str, str] = {}
    for path in candidates:
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values.setdefault(key.strip(), value.strip())
        break
    return values


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _preflight(environment: str, customer_id: str | None) -> None:
    if environment == "prod":
        raise SystemExit("禁止在 prod 环境执行带副作用的回归任务。")
    file_values = _read_env_file(environment)

    def value(name: str) -> str:
        return os.getenv(name, file_values.get(name, ""))

    missing = [
        name
        for name in (
            "ALLOW_BILL_CREATION",
            "CLEANUP_CREATED_BILL",
            "ALLOW_BILL_DELETION",
        )
        if not _truthy(value(name))
    ]
    if missing:
        raise SystemExit(
            "Jenkins 回归为避免遗留数据，以下开关必须显式为 true："
            + ", ".join(missing)
        )
    if customer_id and not customer_id.isdigit():
        raise SystemExit("--customer-id 必须是数字客户号。")


def _run(
    command: list[str], *, env: dict[str, str], timeout_seconds: int | None = None
) -> int:
    print("[CI] " + " ".join(command[1:]))
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        print(f"[CI] 命令超过 {timeout_seconds // 60} 分钟，已停止。")
        return 124
    except KeyboardInterrupt:
        print("[CI] 收到中断，开始执行补偿清理。")
        return 130
    return completed.returncode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="运行云收费 Python Playwright 回归并生成 Jenkins 报告"
    )
    parser.add_argument("--test-env", default=os.getenv("TEST_ENV", "standard1"))
    parser.add_argument("--customer-id", default=os.getenv("CUSTOMER_ID"))
    parser.add_argument("--account-role", default=os.getenv("TEST_ACCOUNT_ROLE"))
    parser.add_argument(
        "--junitxml", type=Path, default=None,
        help="JUnit 输出路径，默认 artifacts/jenkins-junit.xml",
    )
    parser.add_argument(
        "--junit", action="store_true", help="生成 JUnit XML（适用于 Jenkins）",
    )
    parser.add_argument(
        "--html-report", type=Path, default=DEFAULT_HTML,
        help="HTML 报告路径，默认 artifacts/jenkins-regression-report.html",
    )
    parser.add_argument(
        "--headed", action="store_true", help="调试时显示浏览器；Jenkins 默认无头",
    )
    parser.add_argument("--slowmo", type=int, default=0)
    parser.add_argument(
        "--max-minutes", type=int, default=50,
        help="整批 pytest 的最长运行时间，默认 50 分钟；0 表示不设上限",
    )
    parser.add_argument(
        "--shard-index", type=int, default=0,
        help="分片编号，从 0 开始；配合 --shard-count 使用",
    )
    parser.add_argument(
        "--shard-count", type=int, default=1,
        help="分片总数。Jenkins 可创建多个定时任务并行/错峰执行",
    )
    parser.add_argument(
        "--test-target",
        action="append",
        help="选择 pytest 目标；可重复指定多个完整 nodeid，在同一会话串行运行",
    )
    parser.add_argument(
        "--skip-post-cleanup", action="store_true",
        help="仅用于诊断；默认会清理计费出账待处理卡片和临时类账单",
    )
    parser.add_argument(
        "--collect-only", action="store_true",
        help="只收集用例并生成报告，不访问浏览器",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    environment = args.test_env.strip().lower()
    _preflight(environment, args.customer_id)
    if args.max_minutes < 0:
        raise SystemExit("--max-minutes 不能小于 0。")
    if args.shard_count < 1 or not 0 <= args.shard_index < args.shard_count:
        raise SystemExit("--shard-index 必须在 [0, --shard-count) 范围内。")

    artifacts = ROOT / "artifacts"
    artifacts.mkdir(exist_ok=True)
    emit_junit = args.junit or args.junitxml is not None
    internal_junit = not emit_junit
    junit_arg = args.junitxml or (artifacts / ".local-junit-internal.xml")
    junit = (ROOT / junit_arg).resolve() if not junit_arg.is_absolute() else junit_arg
    html_report = (ROOT / args.html_report).resolve() if not args.html_report.is_absolute() else args.html_report
    if args.shard_count > 1 and emit_junit and args.junitxml is None:
        junit = artifacts / f"jenkins-junit-shard-{args.shard_index + 1}.xml"
    if args.shard_count > 1 and args.html_report == DEFAULT_HTML:
        html_report = artifacts / f"jenkins-regression-report-shard-{args.shard_index + 1}.html"
    junit.parent.mkdir(parents=True, exist_ok=True)
    html_report.parent.mkdir(parents=True, exist_ok=True)

    ci_env = os.environ.copy()
    ci_env["TEST_ENV"] = environment
    if args.customer_id:
        ci_env["CUSTOMER_ID"] = args.customer_id.strip()
    if args.account_role:
        ci_env["TEST_ACCOUNT_ROLE"] = args.account_role.strip()
    existing_pythonpath = ci_env.get("PYTHONPATH", "")
    ci_env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(ROOT), str(ROOT / ".tools" / "python"), existing_pythonpath) if part
    )

    common_pytest_args = ["-v", "-p", "scripts.pytest_failure_summary", "--test-env", environment]
    if args.customer_id:
        common_pytest_args.extend(["--customer-id", args.customer_id.strip()])
    if args.account_role:
        common_pytest_args.extend(["--account-role", args.account_role.strip()])

    selected_targets = ["tests/billing"]
    if args.test_target and args.shard_count > 1:
        raise SystemExit("--test-target 不能与 --shard-count 同时使用。")
    if args.test_target:
        selected_targets = args.test_target
    if args.shard_count > 1 and not args.collect_only and not args.test_target:
        collect_command = [
            sys.executable, "-m", "pytest", "tests/billing", "--collect-only", "-q",
            *common_pytest_args,
        ]
        collect = subprocess.run(
            collect_command, cwd=ROOT, env=ci_env, capture_output=True, text=True
        )
        if collect.returncode:
            print(collect.stdout)
            print(collect.stderr)
            return collect.returncode
        nodeids = [
            line.strip()
            for line in collect.stdout.splitlines()
            if re.match(r"^tests[\\/].*::", line.strip())
        ]
        selected_targets = nodeids[args.shard_index :: args.shard_count]
        if not selected_targets:
            raise SystemExit("当前分片没有可执行用例，请检查分片参数。")
        print(
            f"[CI] 分片 {args.shard_index + 1}/{args.shard_count}，"
            f"选择 {len(selected_targets)}/{len(nodeids)} 条用例。"
        )

    pytest_command = [
        sys.executable, "-m", "pytest", *selected_targets,
        *common_pytest_args,
    ]
    pytest_command.extend(["--junitxml", str(junit)])
    if args.headed:
        pytest_command.append("--headed")
    if args.slowmo:
        pytest_command.extend(["--slowmo", str(args.slowmo)])
    if args.collect_only:
        pytest_command.append("--collect-only")

    cleanup_code = 0
    try:
        pytest_code = _run(
            pytest_command,
            env=ci_env,
            timeout_seconds=args.max_minutes * 60 if args.max_minutes else None,
        )
    finally:
        if not args.collect_only and not args.skip_post_cleanup:
            # Per-test finally blocks clean by authoritative bill number.  These
            # two recovery sweeps cover interrupted runs that failed before a
            # bill number or pending-card state could be captured.
            for script in (
                "scripts/cleanup_calculation_pending.py",
                "scripts/cleanup_calculation_temporary_bills.py",
                "scripts/cleanup_bill_center_room_gate.py",
                "scripts/cleanup_temporary_ledger_bills.py",
            ):
                code = _run(
                    [sys.executable, script], env=ci_env, timeout_seconds=600
                )
                cleanup_code = cleanup_code or code

    # HTML generation always consumes the current run's JUnit XML. For local
    # runs this file is temporary; the default output remains HTML + log only.
    ci_env["JUNIT_REPORT_PATH"] = str(junit)
    ci_env["HTML_REPORT_PATH"] = str(html_report)
    report_code = _run([sys.executable, "scripts/generate_html_report.py"], env=ci_env)
    if report_code:
        print(f"[CI] HTML 报告生成失败，退出码={report_code}")
    else:
        print(f"[CI] HTML 报告：{html_report}")

    if internal_junit:
        try:
            junit.unlink(missing_ok=True)
        except OSError as exc:
            print(f"[CI] 临时 JUnit 文件清理失败: {exc}")

    return pytest_code or cleanup_code or report_code


if __name__ == "__main__":
    raise SystemExit(main())
