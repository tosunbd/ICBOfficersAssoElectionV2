"""User accounts: Super Admin, Admin and the three Election Commissioners."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.utils.time import utcnow


class Role:
    SUPERADMIN = "superadmin"  # SA: everything, including deleting ballots and resetting passwords
    ADMIN = "admin"            # Admin: reports, results, election set-up; watches the entry
    EC = "ec"                  # Election Commissioner: enters the ballots of their own number range

    ADMINS = (SUPERADMIN, ADMIN)
    ALL = (SUPERADMIN, ADMIN, EC)


class AdminUser(Base):
    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=True)
    role: Mapped[str] = mapped_column(String(20), default=Role.ADMIN)
    # Ballot paper numbers this Election Commissioner enters (both inclusive); NULL for SA / Admin
    ballot_from: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ballot_to: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    # Relationships
    audit_logs = relationship("AuditLog", back_populates="admin_user")

    @property
    def is_admin(self) -> bool:
        return self.role in Role.ADMINS

    @property
    def is_ec(self) -> bool:
        return self.role == Role.EC
