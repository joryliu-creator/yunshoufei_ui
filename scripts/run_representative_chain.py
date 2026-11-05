"""Run one serial representative per billing entry/type with cleanup gates."""
from __future__ import annotations
import os
import subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = [
    ("bill-center-periodic", "tests/billing/test_create_periodic_center_bills.py::test_create_periodic_bill_and_cleanup[chromium-YSF-BILL-PERIODIC-1002]"),
    ("bill-center-meter", "tests/billing/test_create_meter_bills.py::test_create_meter_bill_and_assert_amount[chromium-YSF-BILL-METER-1032]"),
    ("calc-periodic", "tests/billing/test_calculate_periodic_bill.py::test_calculate_periodic_bill_then_approve_and_cleanup[chromium-YSF-CALC-PERIODIC-1001]"),
    ("calc-meter", "tests/billing/test_calculate_periodic_bill.py::test_calculate_periodic_bill_then_approve_and_cleanup[chromium-YSF-CALC-METER-1032]"),
    ("calc-temporary", "tests/billing/test_calculate_temporary_bill.py::test_calculate_temporary_bill_then_cleanup[chromium-YSF-CALC-TEMP-1016]"),
    ("calc-deposit", "tests/billing/test_create_deposit_bill.py::test_deposit_bill_in_calculation_then_bill_center_cleanup[chromium-YSF-BILL-DEPOSIT-1021]"),
    ("ledger-temporary", "tests/billing/test_create_temporary_bill.py::test_create_temporary_bill_assert_amount_and_cleanup[chromium-YSF-BILL-TEMP-1016]"),
    ("ledger-deposit", "tests/billing/test_create_deposit_bill.py::test_deposit_bill_in_temporary_ledger_then_room_cleanup[chromium-YSF-BILL-DEPOSIT-1021]"),
]

def main() -> int:
    artifacts = ROOT / "artifacts"; artifacts.mkdir(exist_ok=True)
    env = os.environ.copy()
    env.update(BILLING_MONTH="2026-08", CALCULATION_BILLING_MONTH="2026-08")
    cmd = [sys.executable, "scripts/run_jenkins_regression.py", "--test-env", "standard1", "--customer-id", "93537", "--max-minutes", "0", "--junitxml", "artifacts/representative-chain.xml", "--html-report", "artifacts/representative-chain.html"]
    for _, target in TARGETS:
        cmd.extend(["--test-target", target])
    # Collect first: a stale parameter ID must not trigger partial execution.
    collect_cmd = [sys.executable, '-m', 'pytest',
                   *(target for _, target in TARGETS), '--collect-only', '-q',
                   '--test-env', 'standard1', '--customer-id', '93537']
    collected = subprocess.run(collect_cmd, cwd=ROOT, env=env)
    if collected.returncode:
        return collected.returncode
    return subprocess.run(cmd, cwd=ROOT, env=env).returncode

if __name__ == "__main__":
    raise SystemExit(main())
