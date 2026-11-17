"""Application configuration.

All settings can be overridden with environment variables or a `.env` file.
The `.env` file is looked up in the project root (next to "1. Start.bat")
and then inside `icbOfficerAssoAPI/`.

Relative paths are resolved against the PROJECT ROOT, never against the
current working directory, so it does not matter from where uvicorn is started.
"""

import json
import re
from datetime import date
from pathlib import Path
from typing import ClassVar

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

API_DIR = Path(__file__).resolve().parents[1]  # .../icbOfficerAssoAPI
PROJECT_ROOT = API_DIR.parent                   # .../ICBOfficersAssoElectionV2


class Settings(BaseSettings):
    """Runtime settings (see .env.example for documentation of each value)."""

    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", API_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Database ---------------------------------------------------------
    # {Year} is replaced by the election year, so every election gets its own
    # database file (kept afterwards as the record of that election).
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/icbOfficerAssoDB{Year}.db"
    ELECTION_YEAR: int = 0  # 0 = the current calendar year
    # The year chosen in the admin panel (Settings -> Database) is saved here
    # and takes precedence over ELECTION_YEAR.
    DATABASE_SETTINGS_FILE: str = "./data/database_settings.json"

    @field_validator("ELECTION_YEAR", mode="before")
    @classmethod
    def _blank_year(cls, value):
        return 0 if value in ("", None) else value

    # --- Ballot entry -----------------------------------------------------
    # Which ballot paper numbers each Election Commissioner enters:
    #   username:first-last, comma separated.  Applied to the accounts on every start.
    ENTRY_RANGES: str = "EC1:1-150,EC2:151-300,EC3:301-455"
    BALLOT_NUMBER_DIGITS: int = 3        # ballot paper numbers are shown zero-padded: 001, 002 ...
    TOTAL_VOTERS: int = 455              # registered voters of the election created on first start
    # An entry desk counts as "online" in the monitor while it was heard from this recently
    ENTRY_ONLINE_SECONDS: int = 20

    # --- Auth -------------------------------------------------------------
    JWT_SECRET_KEY: str = "icb-election-super-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 720  # 12 hours: one counting day

    # --- HTTP -------------------------------------------------------------
    CORS_ORIGINS: str = "*"             # comma separated list, or * for any origin
    SSE_REFRESH_INTERVAL: int = 2       # seconds between full dashboard refreshes
    LOG_LEVEL: str = "INFO"

    # ---------------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------------
    @staticmethod
    def _resolve(path_str: str) -> Path:
        path = Path(path_str).expanduser()
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path.resolve()

    @property
    def entry_ranges(self) -> dict[str, tuple[int, int]]:
        """{"EC1": (1, 150), ...} parsed from ENTRY_RANGES (bad items are ignored)."""
        ranges: dict[str, tuple[int, int]] = {}
        for item in self.ENTRY_RANGES.split(","):
            match = re.fullmatch(r"\s*([^:\s]+)\s*:\s*(\d+)\s*-\s*(\d+)\s*", item)
            if match and int(match.group(2)) <= int(match.group(3)):
                ranges[match.group(1)] = (int(match.group(2)), int(match.group(3)))
        return ranges

    def format_ballot_no(self, number: int) -> str:
        return str(number).zfill(self.BALLOT_NUMBER_DIGITS)

    # ---------------------------------------------------------------------
    # Database file per election year
    # ---------------------------------------------------------------------
    _YEAR_TOKEN: ClassVar[re.Pattern] = re.compile(r"\{year\}", re.IGNORECASE)
    _database_year: int | None = None  # set from the admin panel / saved file

    @property
    def database_year(self) -> int:
        return self._database_year or self.ELECTION_YEAR or date.today().year

    @property
    def database_url_has_year(self) -> bool:
        return bool(self._YEAR_TOKEN.search(self.DATABASE_URL))

    def database_url_for(self, year: int) -> str:
        return self._resolve_sqlite_url(self._YEAR_TOKEN.sub(str(year), self.DATABASE_URL))

    @property
    def database_url(self) -> str:
        """DATABASE_URL for the current year, relative SQLite paths resolved against the project root."""
        return self.database_url_for(self.database_year)

    @staticmethod
    def sqlite_file(url: str) -> Path | None:
        """The database file behind a SQLite URL (None for other databases / in-memory)."""
        prefix = "sqlite+aiosqlite:///"
        if not url.startswith(prefix) or url[len(prefix):] in ("", ":memory:"):
            return None
        return Path(url[len(prefix):])

    @property
    def database_file(self) -> Path | None:
        return self.sqlite_file(self.database_url)

    @property
    def database_settings_path(self) -> Path:
        return self._resolve(self.DATABASE_SETTINGS_FILE)

    def load_database_year(self) -> None:
        try:
            year = json.loads(self.database_settings_path.read_text(encoding="utf-8")).get("year")
        except (OSError, ValueError, AttributeError):
            return
        if isinstance(year, int) and 2000 <= year <= 2100:
            self._database_year = year

    def save_database_year(self, year: int) -> None:
        self._database_year = year
        path = self.database_settings_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"year": year}, indent=2), encoding="utf-8")

    def _resolve_sqlite_url(self, url: str) -> str:
        prefix = "sqlite+aiosqlite:///"
        if url.startswith(prefix):
            raw = url[len(prefix):]
            if raw and raw != ":memory:" and not Path(raw).is_absolute():
                resolved = self._resolve(raw)
                resolved.parent.mkdir(parents=True, exist_ok=True)
                return prefix + resolved.as_posix()
            if raw and raw != ":memory:":
                Path(raw).parent.mkdir(parents=True, exist_ok=True)
        return url

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


settings = Settings()
settings.load_database_year()
