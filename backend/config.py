import os
from typing import Optional


LOCAL_ENVIRONMENTS = {"development", "dev", "test", "local"}
LOCAL_SECRET_KEY = "pixelcraft-local-development-key-do-not-deploy"
UNSAFE_PLACEHOLDER_KEYS = {
    LOCAL_SECRET_KEY,
    "pixelcraft-secret-key-change-in-production",
    "pixelcraft-change-this-in-production",
}


def get_secret_key(
    environment: Optional[str] = None,
    secret_key: Optional[str] = None,
) -> str:
    """Return a signing key, rejecting unsafe configuration outside local use."""
    current_environment = (environment or os.getenv("APP_ENV", "production")).strip().lower()
    configured_key = secret_key if secret_key is not None else os.getenv("SECRET_KEY")
    configured_key = (configured_key or "").strip()

    if current_environment in LOCAL_ENVIRONMENTS:
        return configured_key or LOCAL_SECRET_KEY
    if not configured_key:
        raise RuntimeError("SECRET_KEY is required outside development and test environments")
    if len(configured_key) < 32:
        raise RuntimeError("SECRET_KEY must contain at least 32 characters outside development")
    if configured_key in UNSAFE_PLACEHOLDER_KEYS:
        raise RuntimeError("SECRET_KEY must not use a documented placeholder value in production")
    return configured_key


APP_ENV = os.getenv("APP_ENV", "production").strip().lower()
SECRET_KEY = get_secret_key(environment=APP_ENV)
