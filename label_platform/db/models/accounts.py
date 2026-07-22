from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from label_platform.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AllowedRoot(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "allowed_roots"

    path: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
