from __future__ import annotations

"""Create then clean the 16 exact AT gas/AC instrument-sharing schemes."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="串行验证燃气表/空调公摊方案的创建和精确清理"
    )
    parser.add_argument("--allow-create", action="store_true")
    parser.add_argument("--allow-cleanup", action="store_true")
    parser.add_argument("--environment", "--test-env", default="standard1")
    parser.add_argument("--customer-id", default="93537")
    parser.add_argument("--account-role", default="default")
    parser.add_argument("--project", default="云收费UI自动化")
    parser.add_argument("--headed", action="store_true")
    return parser.parse_args()


def _run(test_path: str, args: argparse.Namespace, env: dict[str, str]) -> int:
    command = [
        sys.executable,
        "-m",
        "pytest",
        test_path,
        "-q",
        "--test-env",
        args.environment,
        "--customer-id",
        args.customer_id,
        "--account-role",
        args.account_role,
    ]
    if args.headed:
        command.append("--headed")
    return subprocess.run(command, cwd=ROOT, env=env).returncode


def main() -> None:
    args = parse_args()
    if not args.allow_create:
        raise SystemExit("创建是有副作用操作；请显式传入 --allow-create")
    if not args.allow_cleanup:
        raise SystemExit("本回归批次要求精确清理；请显式传入 --allow-cleanup")

    env = os.environ.copy()
    env["ALLOW_PUBLIC_SHARE_SCHEME_CREATION"] = "true"
    env["CLEANUP_PUBLIC_SHARE_SCHEMES"] = "true"
    env["ALLOW_PUBLIC_SHARE_SCHEME_DELETION"] = "true"

    create_rc = _run(
        "tests/billing/test_instrument_public_share_schemes.py", args, env
    )
    # Always run the exact-name AT cleanup phase, even when a creation case
    # fails midway; non-AT water/electric baseline schemes are never targeted.
    cleanup_rc = _run(
        "tests/billing/test_instrument_public_share_scheme_cleanup.py", args, env
    )
    if create_rc:
        raise SystemExit(create_rc)
    raise SystemExit(cleanup_rc)


if __name__ == "__main__":
    main()
