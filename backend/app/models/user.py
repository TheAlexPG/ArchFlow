from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class User(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(255))
    # "local" = email + password, "google" = OAuth via Google, etc.
    # Tracked so users signing in via OAuth can't later accidentally set a
    # password, and vice versa.
    auth_provider: Mapped[str] = mapped_column(String(32), default="local")
