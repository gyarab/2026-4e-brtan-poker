import os

APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
SECRET_KEY = os.getenv("SECRET_KEY", "development-secret-key")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

if ALGORITHM not in {"HS256", "HS384", "HS512"}:
    raise RuntimeError("JWT_ALGORITHM must be HS256, HS384, or HS512")
if ACCESS_TOKEN_EXPIRE_MINUTES < 1:
    raise RuntimeError("ACCESS_TOKEN_EXPIRE_MINUTES must be a positive integer")
if APP_ENV in {"prod", "production"} and (
    SECRET_KEY == "development-secret-key" or len(SECRET_KEY.encode("utf-8")) < 32
):
    raise RuntimeError("Production requires a private SECRET_KEY of at least 32 UTF-8 bytes")
