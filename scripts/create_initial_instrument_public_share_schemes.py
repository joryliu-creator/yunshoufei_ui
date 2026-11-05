from __future__ import annotations

"""Create retained, non-AT water/electric instrument-sharing baselines."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="初始化水表/电表公摊方案（创建后长期保留，不清理）"
    )
    parser.add_argument("--allow-initialization", action="store_true")
    parser.add_argument("--environment", "--test-env", default="standard1")
    parser.add_argument("--customer-id", default="93537")
    parser.add_argument("--account-role", default="default")
    parser.add_argument("--headed", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.allow_initialization:
        raise SystemExit(
            "初始化会创建并保留正式业务方案；请显式传入 --allow-initialization。"
        )

    env = os.environ.copy()
    env["ALLOW_INITIAL_PUBLIC_SHARE_SCHEMES"] = "true"
    command = [
        sys.executable,
        "-m",
        "pytest",
        "tests/billing/test_initial_instrument_public_share_schemes.py",
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
    result = subprocess.run(command, cwd=ROOT, env=env)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
