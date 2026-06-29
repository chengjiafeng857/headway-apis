from dataclasses import dataclass
import os
from pathlib import Path
import socket

from dotenv import load_dotenv

# Load .env from the project root regardless of the current working directory.
# override=False keeps real process env vars authoritative over the file, which
# is the expected precedence (e.g. `AUTO_CREATE_TABLES=true uv run ...` wins).
load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)

_INSECURE_JWT_SECRET = "change-me-in-production"


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./headway.db")
    jwt_secret_key: str = os.getenv("JWT_SECRET_KEY", _INSECURE_JWT_SECRET)
    jwt_expire_minutes: int = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))
    auto_create_tables: bool = os.getenv("AUTO_CREATE_TABLES", "false").lower() == "true"
    environment: str = os.getenv("ENVIRONMENT", "development")
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    redis_notifications_stream: str = os.getenv(
        "REDIS_NOTIFICATIONS_STREAM", "notifications:stream"
    )
    redis_consumer_group: str = os.getenv(
        "REDIS_CONSUMER_GROUP", f"headway-ws-{socket.gethostname()}-{os.getpid()}"
    )
    redis_consumer_name: str = os.getenv("REDIS_CONSUMER_NAME", f"consumer-{os.getpid()}")
    websocket_redis_consumer_enabled: bool = (
        os.getenv("WEBSOCKET_REDIS_CONSUMER_ENABLED", "false").lower() == "true"
    )
    outbox_batch_size: int = int(os.getenv("OUTBOX_BATCH_SIZE", "50"))
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
