from __future__ import annotations

"""创建环境初始化用的周期类公摊方案。

该脚本只创建正式业务方案，不带 AT- 前缀，也不包含任何删除/清理逻辑。
运行前必须显式传入 --allow-initialization，避免被误用于回归清理批次。
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.pages.public_share_scheme_page import (  # noqa: E402
    PublicShareSchemeCase,
    PublicShareSchemePage,
)


CASES = (
    PublicShareSchemeCase(
        case_id="INIT-PUBLIC-SHARE-PERIODIC-RATIO-1201-1202",
        name="UI周期类-按房间设置比例分摊-1201-1202",
        method="按房间设置比例分摊",
        rooms=("1201", "1202"),
        allocations=("40", "60"),
    ),
    PublicShareSchemeCase(
        case_id="INIT-PUBLIC-SHARE-PERIODIC-AMOUNT-1203-1204",
        name="UI周期类-按房间设置金额分摊-1203-1204",
        method="按房间设置金额分摊",
        rooms=("1203", "1204"),
        allocations=("300", "700"),
    ),
    PublicShareSchemeCase(
        case_id="INIT-PUBLIC-SHARE-PERIODIC-BUILDING-1205-1206",
        name="UI周期类-面积系数公摊-建筑面积-1205-1206",
        method="按住户面积及所在楼层对应系数公摊",
        rooms=("1205", "1206"),
        billing_area="建筑面积",
    ),
    PublicShareSchemeCase(
        case_id="INIT-PUBLIC-SHARE-PERIODIC-USABLE-1271-1272",
        name="UI周期类-面积系数公摊-使用面积-1271-1272",
        method="按住户面积及所在楼层对应系数公摊",
        rooms=("1271", "1272"),
        billing_area="使用面积",
    ),
    PublicShareSchemeCase(
        case_id="INIT-PUBLIC-SHARE-PERIODIC-CHARGE-1273-1274",
        name="UI周期类-面积系数公摊-收费面积-1273-1274",
        method="按住户面积及所在楼层对应系数公摊",
        rooms=("1273", "1274"),
        billing_area="收费面积",
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="创建正式周期类公摊方案")
    parser.add_argument("--allow-initialization", action="store_true")
    parser.add_argument("--environment", "--test-env", default="standard1")
    parser.add_argument("--customer-id", default="93537")
    parser.add_argument("--account", "--account-role", dest="account", default="default")
    parser.add_argument("--project", default="云收费UI自动化")
    parser.add_argument("--headful", action="store_true")
    parser.add_argument("--slow-mo", type=int, default=120)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.allow_initialization:
        raise SystemExit("初始化创建需要显式传入 --allow-initialization；本脚本不会执行清理。")

    # Run through the project's proven pytest login fixture.  This keeps one
    # authenticated context for the five cases and avoids a second server-side
    # login session.  The target test contains no cleanup call by design.
    environment = os.environ.copy()
    environment["ALLOW_INITIAL_PUBLIC_SHARE_SCHEMES"] = "true"
    command = [
        sys.executable,
        "-m",
        "pytest",
        "tests/billing/test_initial_public_share_schemes.py",
        "-q",
        "--test-env",
        args.environment,
        "--customer-id",
        args.customer_id,
        "--account-role",
        args.account,
    ]
    if args.headful:
        command.append("--headed")
    result = subprocess.run(command, cwd=ROOT, env=environment)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
