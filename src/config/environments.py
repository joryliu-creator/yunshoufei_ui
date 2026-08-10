from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


SUPPORTED_ENVIRONMENTS = ("standard1", "standard2", "uat", "prod")
ENVIRONMENT_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


def normalize_test_environment(value: str | None) -> str:
    environment = (value or "standard1").strip().lower()
    if not ENVIRONMENT_PATTERN.fullmatch(environment):
        raise ValueError(
            "环境别名只能包含小写字母、数字、下划线和连字符。"
        )
    if environment not in SUPPORTED_ENVIRONMENTS:
        supported = ", ".join(SUPPORTED_ENVIRONMENTS)
        raise ValueError(f"不支持的环境 {environment!r}；可选值：{supported}。")
    return environment


@dataclass(frozen=True, slots=True)
class EnvironmentProfile:
    name: str
    config_file: Path
    uses_legacy_file: bool = False

    @property
    def is_production(self) -> bool:
        return self.name == "prod"


def load_test_environment(
    project_root: Path,
    environment: str | None = None,
    *,
    override: bool = False,
) -> EnvironmentProfile:
    selected = normalize_test_environment(
        environment or os.getenv("TEST_ENV")
    )
    config_file = project_root / f".env.{selected}"
    uses_legacy_file = False

    if selected == "standard1" and not config_file.exists():
        legacy_file = project_root / ".env"
        if legacy_file.exists():
            config_file = legacy_file
            uses_legacy_file = True

    if config_file.exists():
        load_dotenv(config_file, override=override)

    # 选择环境由命令行或调用方决定，不能被配置文件中的旧值覆盖。
    os.environ["TEST_ENV"] = selected
    return EnvironmentProfile(
        name=selected,
        config_file=config_file,
        uses_legacy_file=uses_legacy_file,
    )
