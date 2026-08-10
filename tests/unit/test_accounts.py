from __future__ import annotations

from pathlib import Path

import pytest

from src.config.accounts import (
    account_env_prefix,
    customer_account_env_prefix,
    get_account_auth_profile,
    normalize_account_role,
    normalize_customer_id,
)


def test_normalize_account_role() -> None:
    assert normalize_account_role(" BILLING_ADMIN ") == "billing_admin"
    assert account_env_prefix("finance-admin") == "FINANCE_ADMIN"
    assert normalize_customer_id(" 93537 ") == "93537"
    assert customer_account_env_prefix("93537", "billing-admin") == (
        "C93537_BILLING_ADMIN"
    )


@pytest.mark.parametrize("value", ["../admin", "财务管理员", "a b", ""])
def test_reject_unsafe_account_role(value: str) -> None:
    if value == "":
        assert normalize_account_role(value) == "default"
        return
    with pytest.raises(ValueError):
        normalize_account_role(value)


def test_account_profile_uses_isolated_directory(tmp_path: Path) -> None:
    profile = get_account_auth_profile(
        tmp_path, "cashier", "standard1", "93537"
    )
    assert profile.auth_file == (
        tmp_path / ".auth" / "standard1" / "93537" / "cashier" / "user.json"
    )
    assert profile.session_file == (
        tmp_path
        / ".auth"
        / "standard1"
        / "93537"
        / "cashier"
        / "session-storage.json"
    )
    assert profile.environment == "standard1"
    assert profile.customer_id == "93537"
    assert not profile.uses_legacy_layout


def test_default_profile_falls_back_to_legacy_files(tmp_path: Path) -> None:
    auth_root = tmp_path / ".auth"
    auth_root.mkdir()
    (auth_root / "user.json").write_text("{}", encoding="utf-8")
    (auth_root / "session-storage.json").write_text("{}", encoding="utf-8")

    profile = get_account_auth_profile(tmp_path, "default")

    assert profile.auth_file == auth_root / "user.json"
    assert profile.session_file == auth_root / "session-storage.json"
    assert profile.uses_legacy_layout
