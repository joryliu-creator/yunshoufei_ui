from __future__ import annotations

import os
import re
from pathlib import Path

from src.config.accounts import account_env_prefix, customer_account_env_prefix


def load_local_credentials(
    project_root: Path,
    environment: str,
    customer_id: str,
    role: str,
) -> tuple[str, str, str] | None:
    """Read a scoped local credential without logging or persisting it."""
    scoped_prefix = customer_account_env_prefix(customer_id, role)
    username = os.getenv(f"{scoped_prefix}_USERNAME", "").strip()
    password = os.getenv(f"{scoped_prefix}_PASSWORD", "").strip()
    captcha = os.getenv(f"{scoped_prefix}_CAPTCHA", "").strip()

    is_legacy_standard1 = environment == "standard1" and customer_id == "93537"
    if is_legacy_standard1:
        legacy_prefix = account_env_prefix(role)
        username = username or os.getenv(f"{legacy_prefix}_USERNAME", "").strip()
        password = password or os.getenv(f"{legacy_prefix}_PASSWORD", "").strip()
        captcha = captcha or os.getenv(f"{legacy_prefix}_CAPTCHA", "").strip()
        if role == "default":
            username = username or os.getenv("TEST_USERNAME", "").strip()
            password = password or os.getenv("TEST_PASSWORD", "").strip()
            captcha = captcha or os.getenv("CAPTCHA", "").strip()

    captcha = captcha or "0000"
    if username and password:
        return username, password, captcha

    base_data_file = project_root / "自动化测试基础数据.md"
    if is_legacy_standard1 and role == "default" and base_data_file.exists():
        content = base_data_file.read_text(encoding="utf-8")
        match = re.search(r"测试账号\s*[:：]\s*(\S+)\s+密码\s*[:：]\s*(\S+)", content)
        if match:
            return match.group(1), match.group(2), captcha
    return None
