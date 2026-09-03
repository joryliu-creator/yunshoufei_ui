"""Run one serial representative per billing entry/type with cleanup gates."""
from __future__ import annotations
import os
import subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = [
    ("bill-center-periodic", "tests/billing/test_create_periodic_center_bills.py::test_create_periodic_bill_and_cleanup[chromium-YSF-BILL-PERIODIC-1002]"),
    ("bill-center-meter", "tests/billing/test_create_meter_bills.py::test_create_meter_bill_and_assert_amount[chromium-YSF-BILL-METER-1032]"),
    ("calc-periodic", "tests/billing/test_calculate_periodic_bill.py::test_calculate_periodic_bill_then_approve_and_cleanup[chromium-YSF-CALC-001]"),
    ("calc-meter", "tests/billing/test_calculate_periodic_bill.py::test_calculate_periodic_bill_then_approve_and_cleanup[chromium-YSF-CALC-METER-1032]"),
    ("calc-temporary", "tests/billing/test_calculate_temporary_bill.py::test_calculate_temporary_bill_then_cleanup[chromium-YSF-CALC-TEMP-1016]"),
    ("calc-deposit", "tests/billing/test_create_deposit_bill.py::test_deposit_bill_in_calculation_then_bill_center_cleanup[chromium-YSF-BILL-DEPOSIT-001]"),
    ("ledger-temporary", "tests/billing/test_create_temporary_bill.py::test_create_temporary_bill_assert_amount_and_cleanup"),
    ("ledger-deposit", "tests/billing/test_create_deposit_bill.py::test_deposit_bill_in_temporary_ledger_then_room_cleanup[chromium-YSF-BILL-DEPOSIT-001]"),
]

def main() -> int:
    artifacts = ROOT / "artifacts"; artifacts.mkdir(exist_ok=True)
    env = os.environ.copy()
    env.update(BILLING_MONTH="2026-08", CALCULATION_BILLING_MONTH="2026-08", RECEIVABLE_DATE="2026-08-01", LATEST_PAYMENT_DATE="2026-08-01")
    results = []
    for name, target in TARGETS:
        log = artifacts / f"representative-{name}.log"
        target_env = env.copy()
        if name == "ledger-temporary":
            # Do not inherit the default periodic demo case from .env; this
            # entrypoint must resolve the dedicated temporary-ledger scenario.
            target_env["TEST_CASE_ID"] = "YSF-BILL-TEMP-001"
            target_env["SCENARIO_ID"] = "YSF-SCENE-TEMP-LEDGER-1016"
        cmd = [sys.executable, "scripts/run_jenkins_regression.py", "--test-env", "standard1", "--customer-id", "93537", "--test-target", target, "--max-minutes", "10", "--junitxml", f"artifacts/representative-{name}.xml", "--html-report", f"artifacts/representative-{name}.html"]
        with log.open("w", encoding="utf-8") as stream:
            code = subprocess.run(cmd, cwd=ROOT, env=target_env, stdout=stream, stderr=subprocess.STDOUT).returncode
        results.append((name, code))
        # The runner performs per-test and post-test cleanup before continuing.
    print("; ".join(f"{name}={'PASS' if code == 0 else 'FAIL'}" for name, code in results))
    return 0 if all(code == 0 for _, code in results) else 1

if __name__ == "__main__":
    raise SystemExit(main())
