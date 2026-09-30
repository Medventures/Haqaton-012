"""Explicit runtime settings. Secrets never enter the public configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import re
import secrets
from urllib.parse import urlsplit


PROJECT = Path(__file__).resolve().parent
_DEVELOPMENT_SECRET = secrets.token_urlsafe(48)


def _dotenv(path: Path) -> dict[str, str]:
    """Literal-only dotenv reader: no interpolation or shell execution."""
    if not path.is_file():
        return {}
    result = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, value = line.partition("=")
        if not separator or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key.strip()):
            raise ValueError(f"Проверьте имя переменной в .env, строка {number}.")
        value = value.strip()
        if value[:1] in ("'", '"'):
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError(f"Проверьте кавычки в .env, строка {number}.")
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].rstrip()
        result[key.strip()] = value
    return result


def _number(values, key, default, minimum, maximum, convert=int):
    try:
        value = convert(values.get(key, default))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Проверьте значение {key}.") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"Значение {key} должно быть от {minimum} до {maximum}.")
    return value


def _boolean(values, key, default):
    value = str(values.get(key, str(default))).lower()
    if value not in ("1", "0", "true", "false"):
        raise ValueError(f"Укажите true или false для {key}.")
    return value in ("1", "true")


@dataclass(frozen=True)
class Settings:
    api_key: str = field(default="", repr=False)
    model: str = "gpt-5-mini"
    api_timeout: float = 35.0
    signing_secret: str = field(default=_DEVELOPMENT_SECRET, repr=False)
    agent_enabled: bool = True
    environment: str = "development"
    host: str = "127.0.0.1"
    port: int = 8000
    allowed_origins: tuple[str, ...] = ("http://127.0.0.1:8000", "http://localhost:8000")
    rate_limit: int = 20
    rate_window: int = 60
    max_concurrent_agents: int = 4
    max_body_bytes: int = 32768
    threads: int = 8
    admin_token: str = field(default="", repr=False)
    metrics_db: Path = PROJECT / "data" / "metrics.sqlite3"

    @property
    def ai_available(self) -> bool:
        return self.agent_enabled and bool(self.api_key)


def load_settings(project: Path | None = None, environ: dict | None = None) -> Settings:
    project = (project or PROJECT).resolve()
    env_file = project / ".env"
    # Compatibility with this workspace's nested clone; never search arbitrary ancestors.
    if not env_file.is_file() and project.name.lower() == "medhub_checkup" and (project.parent / "server.py").is_file():
        env_file = project.parent / ".env"
    values = _dotenv(env_file)
    values.update(os.environ if environ is None else environ)
    environment = values.get("MEDHUB_ENV", "development").lower()
    if environment not in ("development", "production", "test"):
        raise ValueError("MEDHUB_ENV должен быть development, production или test.")
    port = _number(values, "MEDHUB_PORT", 8000, 1, 65535)
    origins = tuple(item.strip().rstrip("/") for item in values.get("MEDHUB_ALLOWED_ORIGINS", "").split(",") if item.strip())
    if not origins and environment != "production":
        origins = (f"http://127.0.0.1:{port}", f"http://localhost:{port}")
    if not origins:
        raise ValueError("В production задайте MEDHUB_ALLOWED_ORIGINS — адрес сайта с https://.")
    for origin in origins:
        parsed = urlsplit(origin)
        try:
            parsed.port
        except ValueError as exc:
            raise ValueError("Проверьте адрес в MEDHUB_ALLOWED_ORIGINS.") from exc
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment or "*" in origin:
            raise ValueError("MEDHUB_ALLOWED_ORIGINS должен содержать точные адреса без пути и масок.")
        if environment == "production" and parsed.scheme != "https":
            raise ValueError("В production адрес MEDHUB_ALLOWED_ORIGINS должен начинаться с https://.")
    secret = values.get("MEDHUB_SIGNING_SECRET", "")
    if environment == "production" and (len(secret) < 32 or len(set(secret)) < 12 or secret.lower().startswith(("change", "replace", "example"))):
        raise ValueError("В production задайте случайный MEDHUB_SIGNING_SECRET длиной не менее 32 символов.")
    model = values.get("OPENAI_MODEL", "gpt-5-mini").strip()
    if not re.fullmatch(r"[a-zA-Z0-9._:-]{1,100}", model):
        raise ValueError("Проверьте OPENAI_MODEL.")
    admin_token = values.get("ADMIN_TOKEN", "").strip()
    if admin_token and (len(admin_token) < 32 or len(set(admin_token)) < 12):
        raise ValueError("ADMIN_TOKEN должен быть случайной строкой длиной не менее 32 символов.")
    # API destination is intentionally not configurable: never send a key to a custom host.
    return Settings(
        api_key=values.get("OPENAI_API_KEY", "").strip(), model=model,
        api_timeout=_number(values, "OPENAI_TIMEOUT_SECONDS", 35, 5, 90, float),
        signing_secret=secret or _DEVELOPMENT_SECRET,
        agent_enabled=_boolean(values, "MEDHUB_AGENT_ENABLED", True),
        environment=environment, host=values.get("MEDHUB_HOST", "127.0.0.1"), port=port,
        allowed_origins=origins,
        rate_limit=_number(values, "MEDHUB_RATE_LIMIT", 20, 1, 300),
        rate_window=_number(values, "MEDHUB_RATE_WINDOW_SECONDS", 60, 10, 3600),
        max_concurrent_agents=_number(values, "MEDHUB_MAX_CONCURRENT_AGENTS", 4, 1, 32),
        threads=_number(values, "MEDHUB_THREADS", 8, 4, 64),
        admin_token=admin_token, metrics_db=Path(values.get("MEDHUB_METRICS_DB", str(project / "data" / "metrics.sqlite3"))),
    )
