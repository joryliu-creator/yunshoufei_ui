from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


ACCOUNT_ROLE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


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


@dataclass(frozen=True, slots=True)
class AccountAuthProfile:
    role: str
    auth_file: Path
    session_file: Path
    uses_legacy_layout: bool = False


def get_account_auth_profile(
    project_root: Path,
    role: str,
    *,
    allow_legacy_default: bool = True,
) -> AccountAuthProfile:
    normalized_role = normalize_account_role(role)
    auth_root = project_root / ".auth"
    account_root = auth_root / normalized_role
    profile = AccountAuthProfile(
        role=normalized_role,
        auth_file=account_root / "user.json",
        session_file=account_root / "session-storage.json",
    )

    if normalized_role != "default" or not allow_legacy_default:
        return profile

    legacy_auth = auth_root / "user.json"
    legacy_session = auth_root / "session-storage.json"
    if (
        not profile.auth_file.exists()
        and not profile.session_file.exists()
        and legacy_auth.exists()
        and legacy_session.exists()
    ):
        return AccountAuthProfile(
            role=normalized_role,
            auth_file=legacy_auth,
            session_file=legacy_session,
            uses_legacy_layout=True,
        )
    return profile
