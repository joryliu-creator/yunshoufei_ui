from __future__ import annotations

from pathlib import Path

import pytest

import src.config.settings as settings_module
from src.config.environments import EnvironmentProfile
from src.config.settings import _environment_value


def test_standard1_has_known_safe_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BASE_URL", raising=False)
    assert _environment_value("BASE_URL", "standard1", "known") == "known"


def test_standard1_default_base_url_uses_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        settings_module,
        "environment_profile",
        EnvironmentProfile("standard1", Path(".env.standard1")),
    )
    monkeypatch.delenv("BASE_URL", raising=False)
    monkeypatch.delenv("CUSTOMER_ID", raising=False)
    monkeypatch.delenv("MASTER_CUSTOMER_ID", raising=False)
    monkeypatch.setenv("ALLOW_BILL_CREATION", "false")
    monkeypatch.setenv("CLEANUP_CREATED_BILL", "false")
    monkeypatch.setenv("ALLOW_BILL_DELETION", "false")

    created = settings_module.Settings.from_env()

    assert created.base_url == "http://t.jslife.net/jportal/index.html"
    assert created.master_customer_id == "93537"


def test_other_environment_requires_explicit_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BASE_URL", raising=False)
    with pytest.raises(RuntimeError, match=r"\.env\.uat"):
        _environment_value("BASE_URL", "uat", "standard1-only")


def test_production_rejects_side_effect_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        settings_module,
        "environment_profile",
        EnvironmentProfile("prod", Path(".env.prod")),
    )
    monkeypatch.setenv("BASE_URL", "https://prod.invalid/jportal/index.html")
    monkeypatch.setenv("CUSTOMER_ID", "prod-check")
    monkeypatch.setenv("ALLOW_BILL_CREATION", "true")

    with pytest.raises(RuntimeError, match="生产环境禁止"):
        settings_module.Settings.from_env()
