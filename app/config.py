import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite+aiosqlite:///app/data/app.db"
    SQL_SETUP_FILE: str = "data_table_setup.sql"
    TILE_CACHE_DIR: str = "/app/data/tiles"
    SECRET_KEY: str = "super-secret-key-change-me"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 1 week

    class Config:
        env_file = ".env"

settings = Settings()

# Create cache dir if it doesn't exist locally for development
try:
    os.makedirs(settings.TILE_CACHE_DIR, exist_ok=True)
except OSError:
    # This might fail on read-only file systems during build or in some restricted envs
    pass
