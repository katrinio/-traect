from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from traect.db.base import Base
from traect.domain.enums import WeekDomainMode, WeekDomainStatus


class Workspace(Base):
    __tablename__ = "workspace"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, init=False)
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), init=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), init=False, server_default=func.now(), onupdate=func.now()
    )

    domains: Mapped[list[Domain]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan", default_factory=list
    )
    weeks: Mapped[list[Week]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan", default_factory=list
    )


class Domain(Base):
    __tablename__ = "domain"
    __table_args__ = (
        Index(
            "uq_domain_workspace_active_name",
            "workspace_id",
            "name",
            unique=True,
            sqlite_where=text("archived_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, init=False)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"), index=True, init=False)
    name: Mapped[str] = mapped_column(String(120))
    sort_order: Mapped[int] = mapped_column(Integer)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), init=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), init=False, server_default=func.now(), onupdate=func.now()
    )

    workspace: Mapped[Workspace] = relationship(back_populates="domains", init=False)
    week_states: Mapped[list[WeekDomainState]] = relationship(back_populates="domain", default_factory=list)


class Week(Base):
    __tablename__ = "week"
    __table_args__ = (UniqueConstraint("workspace_id", "iso_year", "iso_week", name="uq_week_workspace_iso_week"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, init=False)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"), index=True, init=False)
    iso_year: Mapped[int] = mapped_column(Integer)
    iso_week: Mapped[int] = mapped_column(Integer)
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date] = mapped_column(Date)
    focus_domain_id: Mapped[int | None] = mapped_column(
        ForeignKey("domain.id", ondelete="SET NULL"), nullable=True, default=None
    )
    sacrificed_domain_id: Mapped[int | None] = mapped_column(
        ForeignKey("domain.id", ondelete="SET NULL"), nullable=True, default=None
    )
    sacrifice_reason: Mapped[str | None] = mapped_column(String(240), nullable=True, default=None)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), init=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), init=False, server_default=func.now(), onupdate=func.now()
    )

    workspace: Mapped[Workspace] = relationship(back_populates="weeks", init=False)
    domain_states: Mapped[list[WeekDomainState]] = relationship(
        back_populates="week", cascade="all, delete-orphan", default_factory=list
    )
    focus_domain: Mapped[Domain | None] = relationship(foreign_keys=[focus_domain_id], init=False, post_update=True)
    sacrificed_domain: Mapped[Domain | None] = relationship(
        foreign_keys=[sacrificed_domain_id], init=False, post_update=True
    )


class WeekDomainState(Base):
    __tablename__ = "week_domain_state"
    __table_args__ = (UniqueConstraint("week_id", "domain_id", name="uq_week_domain_state_week_domain"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, init=False)
    week_id: Mapped[int] = mapped_column(ForeignKey("week.id", ondelete="CASCADE"), index=True, init=False)
    domain_id: Mapped[int] = mapped_column(ForeignKey("domain.id", ondelete="CASCADE"), index=True, init=False)
    status: Mapped[WeekDomainStatus] = mapped_column(
        Enum(WeekDomainStatus, name="week_domain_status", native_enum=False)
    )
    mode: Mapped[WeekDomainMode] = mapped_column(Enum(WeekDomainMode, name="week_domain_mode", native_enum=False))
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), init=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), init=False, server_default=func.now(), onupdate=func.now()
    )

    week: Mapped[Week] = relationship(back_populates="domain_states", init=False)
    domain: Mapped[Domain] = relationship(back_populates="week_states", init=False)
