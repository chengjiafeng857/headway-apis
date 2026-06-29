from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from typing import Any

from dotenv import load_dotenv

# Load .env from the project root regardless of the current working directory.
# override=False keeps real process env vars authoritative over the file, which
# is the expected precedence (e.g. `AUTO_CREATE_TABLES=true uv run ...` wins).
load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)

_INSECURE_JWT_SECRET = "change-me-in-production"


class OAuthConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class OAuthProviderConfig:
    name: str
    client_id: str
    client_secret: str
    authorization_url: str
    token_url: str
    userinfo_url: str
    scopes: tuple[str, ...] = ("openid", "email", "profile")
    require_verified_email: bool = True


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./headway.db")
    jwt_secret_key: str = os.getenv("JWT_SECRET_KEY", _INSECURE_JWT_SECRET)
    jwt_expire_minutes: int = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))
    auto_create_tables: bool = os.getenv("AUTO_CREATE_TABLES", "false").lower() == "true"
    environment: str = os.getenv("ENVIRONMENT", "development")
    # Run the in-process outbox dispatcher that pushes notifications to connected
    # WebSocket sockets. Must run inside the API process (delivery is in-memory).
    realtime_dispatch_enabled: bool = (
        os.getenv("REALTIME_DISPATCH_ENABLED", "false").lower() == "true"
    )
    outbox_batch_size: int = int(os.getenv("OUTBOX_BATCH_SIZE", "50"))
    outbox_poll_seconds: float = float(os.getenv("OUTBOX_POLL_SECONDS", "1.0"))
    # DB_ECHO logs every SQL statement; DB_ECHO_POOL logs connection pool
    # activity (connect / checkout / checkin). Keep both off in production.
    db_echo: bool = os.getenv("DB_ECHO", "false").lower() == "true"
    db_echo_pool: bool = os.getenv("DB_ECHO_POOL", "false").lower() == "true"

    def __post_init__(self) -> None:
        # Refuse to start in production with the placeholder signing key, which
        # would let anyone forge valid JWTs.
        if self.environment == "production" and self.jwt_secret_key == _INSECURE_JWT_SECRET:
            raise RuntimeError(
                "JWT_SECRET_KEY must be set to a strong secret when ENVIRONMENT=production"
            )


settings = Settings()


def _normalize_oauth_provider_name(provider: str) -> str:
    normalized = provider.strip().lower()
    if not re.fullmatch(r"[a-z0-9_-]{1,50}", normalized):
        raise OAuthConfigurationError("OAuth provider names may contain letters, numbers, _ and -")
    return normalized


def _oauth_env_prefix(provider: str) -> str:
    return f"OAUTH_{provider.upper().replace('-', '_')}_"


def _parse_oauth_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _parse_oauth_scopes(value: Any) -> tuple[str, ...]:
    if value is None:
        return ("openid", "email", "profile")
    if isinstance(value, str):
        normalized = value.replace(",", " ")
        return tuple(scope for scope in normalized.split() if scope)
    if isinstance(value, list):
        return tuple(str(scope).strip() for scope in value if str(scope).strip())
    raise OAuthConfigurationError("OAuth scopes must be a string or list of strings")


def _oauth_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _oauth_provider_from_mapping(
    provider: str, mapping: dict[str, Any]
) -> OAuthProviderConfig | None:
    provider_config = None
    for configured_name, configured_value in mapping.items():
        if _normalize_oauth_provider_name(configured_name) == provider:
            provider_config = configured_value
            break
    if provider_config is None:
        return None
    if not isinstance(provider_config, dict):
        raise OAuthConfigurationError(f"OAuth provider '{provider}' must be an object")

    return OAuthProviderConfig(
        name=provider,
        client_id=_oauth_text(provider_config.get("client_id")),
        client_secret=_oauth_text(provider_config.get("client_secret")),
        authorization_url=_oauth_text(provider_config.get("authorization_url")),
        token_url=_oauth_text(provider_config.get("token_url")),
        userinfo_url=_oauth_text(provider_config.get("userinfo_url")),
        scopes=_parse_oauth_scopes(provider_config.get("scopes")),
        require_verified_email=_parse_oauth_bool(
            provider_config.get("require_verified_email"),
            True,
        ),
    )


def _oauth_provider_from_env(provider: str) -> OAuthProviderConfig:
    prefix = _oauth_env_prefix(provider)
    authorization_url = os.getenv(f"{prefix}AUTHORIZATION_URL", "").strip()
    token_url = os.getenv(f"{prefix}TOKEN_URL", "").strip()
    userinfo_url = os.getenv(f"{prefix}USERINFO_URL", "").strip()

    if provider == "google":
        authorization_url = authorization_url or "https://accounts.google.com/o/oauth2/v2/auth"
        token_url = token_url or "https://oauth2.googleapis.com/token"
        userinfo_url = userinfo_url or "https://openidconnect.googleapis.com/v1/userinfo"

    return OAuthProviderConfig(
        name=provider,
        client_id=os.getenv(f"{prefix}CLIENT_ID", "").strip(),
        client_secret=os.getenv(f"{prefix}CLIENT_SECRET", "").strip(),
        authorization_url=authorization_url,
        token_url=token_url,
        userinfo_url=userinfo_url,
        scopes=_parse_oauth_scopes(os.getenv(f"{prefix}SCOPES")),
        require_verified_email=_parse_oauth_bool(
            os.getenv(f"{prefix}REQUIRE_VERIFIED_EMAIL"),
            True,
        ),
    )


def get_oauth_provider_config(provider: str) -> OAuthProviderConfig:
    normalized = _normalize_oauth_provider_name(provider)
    providers_json = os.getenv("OAUTH_PROVIDERS_JSON", "").strip()
    config: OAuthProviderConfig | None = None
    if providers_json:
        try:
            parsed = json.loads(providers_json)
        except json.JSONDecodeError as exc:
            raise OAuthConfigurationError("OAUTH_PROVIDERS_JSON is not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise OAuthConfigurationError("OAUTH_PROVIDERS_JSON must be a provider object map")
        config = _oauth_provider_from_mapping(normalized, parsed)

    config = config or _oauth_provider_from_env(normalized)
    missing = [
        field
        for field in (
            "client_id",
            "client_secret",
            "authorization_url",
            "token_url",
            "userinfo_url",
        )
        if not getattr(config, field)
    ]
    if missing:
        raise OAuthConfigurationError(
            f"OAuth provider '{normalized}' is not configured: missing {', '.join(missing)}"
        )
    if not config.scopes:
        raise OAuthConfigurationError(f"OAuth provider '{normalized}' must define at least one scope")
    return config
