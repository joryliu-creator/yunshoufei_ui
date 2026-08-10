from __future__ import annotations

from pathlib import Path

import pytest

from src.config.environments import (
    load_test_environment,
    normalize_test_environment,
)


def test_normalize_supported_environment() -> None:
    assert normalize_test_environment(" STANDARD1 ") == "standard1"
    assert normalize_test_environment("uat") == "uat"


@pytest.mark.parametrize("value", ["dev", "standard 1", "../prod"])
def test_reject_unknown_or_unsafe_environment(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_test_environment(value)


def test_standard1_can_fall_back_to_legacy_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    legacy = tmp_path / ".env"
    legacy.write_text("CUSTOMER_ID=93537\n", encoding="utf-8")
    monkeypatch.delenv("CUSTOMER_ID", raising=False)

    profile = load_test_environment(tmp_path, "standard1", override=True)

    assert profile.config_file == legacy
    assert profile.uses_legacy_file


def test_environment_specific_file_is_preferred(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    specific = tmp_path / ".env.uat"
    specific.write_text("CUSTOMER_ID=uat-customer\n", encoding="utf-8")
    monkeypatch.delenv("CUSTOMER_ID", raising=False)

    profile = load_test_environment(tmp_path, "uat", override=True)

    assert profile.config_file == specific
    assert not profile.uses_legacy_file
    assert not profile.is_production


def test_production_profile_is_identified(tmp_path: Path) -> None:
    profile = load_test_environment(tmp_path, "prod")
    assert profile.is_production
