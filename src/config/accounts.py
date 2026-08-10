from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from src.config.environments import normalize_test_environment


ACCOUNT_ROLE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
CUSTOMER_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def normalize_account_role(value: str | None) -> str:
    role = (value or "default").strip().lower()
    if not ACCOUNT_ROLE_PATTERN.fullmatch(role):
        raise ValueError(
            "账号别名只能包含小写字母、数字、下划线和连字符，"
            "长度为 1-64 个字符。"
        )
    return role


def account_env_prefix(role: str) -> str:
    return normalize_account_role(role).replace("-", "_").upper()


def normalize_customer_id(value: str | None) -> str:
    customer_id = (value or "").strip()
    if not CUSTOMER_ID_PATTERN.fullmatch(customer_id):
        raise ValueError(
            "客户号只能包含字母、数字、下划线和连字符，且不能为空。"
        )
    return customer_id


def customer_account_env_prefix(customer_id: str, role: str) -> str:
    normalized_customer = normalize_customer_id(customer_id).replace("-", "_")
    return f"C{normalized_customer}_{account_env_prefix(role)}".upper()


@dataclass(frozen=True, slots=True)
class AccountAuthProfile:
    environment: str
    customer_id: str
    role: str
    auth_file: Path
    session_file: Path
    uses_legacy_layout: bool = False


def get_account_auth_profile(
    project_root: Path,
    role: str,
    environment: str = "standard1",
    customer_id: str = "93537",
    *,
    allow_legacy_default: bool = True,
) -> AccountAuthProfile:
    normalized_role = normalize_account_role(role)
    normalized_environment = normalize_test_environment(environment)
    normalized_customer = normalize_customer_id(customer_id)
    auth_root = project_root / ".auth"
    account_root = (
        auth_root
        / normalized_environment
        / normalized_customer
        / normalized_role
    )
    profile = AccountAuthProfile(
        environment=normalized_environment,
        customer_id=normalized_customer,
        role=normalized_role,
        auth_file=account_root / "user.json",
        session_file=account_root / "session-storage.json",
    )

    if normalized_environment != "standard1" or not allow_legacy_default:
        return profile

    legacy_candidates = [
        auth_root / normalized_environment / normalized_role,
        auth_root / normalized_role,
    ]
    if normalized_role == "default":
        legacy_candidates.append(auth_root)
    if not profile.auth_file.exists() and not profile.session_file.exists():
        for candidate in legacy_candidates:
            legacy_auth = candidate / "user.json"
            legacy_session = candidate / "session-storage.json"
            if legacy_auth.exists() and legacy_session.exists():
                return AccountAuthProfile(
                    environment=normalized_environment,
                    customer_id=normalized_customer,
                    role=normalized_role,
                    auth_file=legacy_auth,
                    session_file=legacy_session,
                    uses_legacy_layout=True,
                )
    return profile
