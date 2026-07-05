from datetime import datetime
from typing import Optional
from sqlalchemy import String, Boolean, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String)
    bearer_token: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

class CachedTile(Base):
    __tablename__ = "cached_tiles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tile_id: Mapped[str] = mapped_column(String, unique=True)
    file_path: Mapped[str] = mapped_column(String)
    last_used_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
