"""Settings loaded from the environment (.env). Import `load_settings()` rather than reading os.environ directly."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str = field(repr=False)
    model: str
    db_path: Path
    tax_math_mcp_url: str
    max_review_passes: int
    loop_guard_repeats: int
    log_level: str
    tax_math_mcp_host: str = "127.0.0.1"


def load_settings() -> Settings:
    load_dotenv(ROOT / ".env")
    db_path = Path(os.getenv("SILVERFILE_DB_PATH", "data/silverfile.sqlite"))
    if not db_path.is_absolute():
        db_path = ROOT / db_path
    return Settings(
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        model=os.getenv("SILVERFILE_MODEL", "claude-sonnet-5-5"),
        db_path=db_path,
        tax_math_mcp_url=os.getenv("TAX_MATH_MCP_URL", ""),  # empty: tax_math runs in-process
        max_review_passes=int(os.getenv("SILVERFILE_MAX_REVIEW_PASSES", "3")),
        loop_guard_repeats=int(os.getenv("SILVERFILE_LOOP_GUARD_REPEATS", "3")),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        tax_math_mcp_host=os.getenv("TAX_MATH_MCP_HOST", "127.0.0.1"),
    )
