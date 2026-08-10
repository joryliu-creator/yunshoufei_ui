from __future__ import annotations

import pytest

from scripts.save_auth import load_credentials


def test_customer_scoped_credentials_are_loaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("C93537_CASHIER_USERNAME", "scoped-user")
    monkeypatch.setenv("C93537_CASHIER_PASSWORD", "scoped-password")
    monkeypatch.setenv("C93537_CASHIER_CAPTCHA", "0000")

    assert load_credentials("standard1", "93537", "cashier") == (
        "scoped-user",
        "scoped-password",
        "0000",
    )


def test_other_customer_does_not_reuse_legacy_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CASHIER_USERNAME", "legacy-user")
    monkeypatch.setenv("CASHIER_PASSWORD", "legacy-password")
    monkeypatch.delenv("COTHER_CASHIER_USERNAME", raising=False)
    monkeypatch.delenv("COTHER_CASHIER_PASSWORD", raising=False)

    assert load_credentials("uat", "other", "cashier") is None
