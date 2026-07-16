from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
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

    domains: Mapped[list["Domain"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan", default_factory=list
    )
    weeks: Mapped[list["Week"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan", default_factory=list
    )


class Domain(Base):
    __tablename__ = "domain"
    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_domain_workspace_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, init=False)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"), index=True, init=False)
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), init=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), init=False, server_default=func.now(), onupdate=func.now()
    )

    workspace: Mapped[Workspace] = relationship(back_populates="domains", init=False)
    week_states: Mapped[list["WeekDomainState"]] = relationship(
        back_populates="domain", cascade="all, delete-orphan", default_factory=list
    )


class Week(Base):
    __tablename__ = "week"
    __table_args__ = (UniqueConstraint("workspace_id", "iso_year", "iso_week", name="uq_week_workspace_iso_week"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, init=False)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"), index=True, init=False)
    iso_year: Mapped[int] = mapped_column(Integer)
    iso_week: Mapped[int] = mapped_column(Integer)
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date] = mapped_column(Date)
    focus_domain_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sacrificed_domain_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sacrifice_reason: Mapped[str | None] = mapped_column(String(240), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), init=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), init=False, server_default=func.now(), onupdate=func.now()
    )

    workspace: Mapped[Workspace] = relationship(back_populates="weeks", init=False)
    domain_states: Mapped[list["WeekDomainState"]] = relationship(
        back_populates="week", cascade="all, delete-orphan", default_factory=list
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
