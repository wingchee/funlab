from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import relationship
from database import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "NOT is_permanently_archived OR "
            "(NOT is_active AND phone IS NULL AND balance_access_token IS NULL)",
            name="ck_users_permanent_archive_invariants",
        ),
    )
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    name = Column(String, nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)
    member_code = Column(String, unique=True, nullable=True, index=True)
    balance_access_token = Column(String, unique=True, nullable=True, index=True)
    phone = Column(String, unique=True, nullable=True, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    is_permanently_archived = Column(Boolean, default=False, nullable=False)
    notes = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    favorites = relationship("Favorite", back_populates="user", cascade="all, delete-orphan")
    packages = relationship("MemberPackage", back_populates="member", cascade="all, delete-orphan")
    visits = relationship("MemberVisit", back_populates="member", cascade="all, delete-orphan")


class MemberPackage(Base):
    __tablename__ = "member_packages"
    id = Column(Integer, primary_key=True)
    member_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    package_name = Column(String, nullable=False)
    total_seconds = Column(Integer, nullable=False)
    remaining_seconds = Column(Integer, nullable=False)
    notes = Column(Text, nullable=False, default="")
    purchased_at = Column(DateTime, server_default=func.now(), index=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    member = relationship("User", back_populates="packages")


class MemberVisit(Base):
    __tablename__ = "member_visits"
    id = Column(Integer, primary_key=True)
    member_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    table_time_log_id = Column(
        Integer,
        ForeignKey("table_time_logs.id"),
        nullable=True,
        unique=True,
        index=True,
    )
    table_number = Column(Integer, nullable=False, index=True)
    checked_in_at = Column(DateTime, nullable=False, index=True)
    checked_out_at = Column(DateTime, nullable=False, index=True)
    occupied_seconds = Column(Integer, default=0, nullable=False)
    charged_seconds = Column(Integer, default=0, nullable=False)
    package_deducted_seconds = Column(Integer, default=0, nullable=False)
    extra_due_seconds = Column(Integer, default=0, nullable=False)
    notes = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, server_default=func.now())
    member = relationship("User", back_populates="visits")
    table_time_log = relationship("TableTimeLog", back_populates="member_visit")


class Pattern(Base):
    __tablename__ = "patterns"
    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    tags = Column(Text, nullable=False, default="[]")        # JSON list of strings
    size = Column(String, nullable=False)                     # Small | Medium | Large
    grid_w = Column(Integer, nullable=False)
    grid_h = Column(Integer, nullable=False)
    faves_count = Column(Integer, default=0)
    preview_color = Column(String, nullable=False, default="#CC2936")
    palette = Column(Text, nullable=False, default="[]")      # JSON: [{id, name, hex}]
    grid_data = Column(Text, nullable=False, default="[]")    # JSON: 2-D array of bead IDs
    created_at = Column(DateTime, server_default=func.now())
    favorites = relationship("Favorite", back_populates="pattern", cascade="all, delete-orphan")


class Favorite(Base):
    __tablename__ = "favorites"
    __table_args__ = (
        Index("uq_favorites_user_pattern", "user_id", "pattern_id", unique=True),
    )
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    pattern_id = Column(Integer, ForeignKey("patterns.id"), nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    user = relationship("User", back_populates="favorites")
    pattern = relationship("Pattern", back_populates="favorites")


class TableTimer(Base):
    __tablename__ = "table_timers"
    id = Column(Integer, primary_key=True)
    table_number = Column(Integer, unique=True, nullable=False, index=True)
    is_running = Column(Boolean, default=False, nullable=False)
    elapsed_seconds = Column(Integer, default=0, nullable=False)
    started_at = Column(DateTime, nullable=True)
    run_token = Column(String, nullable=True)
    state_version = Column(Integer, default=0, nullable=False)
    active_member_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    active_member_started_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    active_member = relationship("User")


class TableTimeLog(Base):
    __tablename__ = "table_time_logs"
    id = Column(Integer, primary_key=True)
    table_number = Column(Integer, nullable=False, index=True)
    member_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    member_started_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=False, index=True)
    ended_at = Column(DateTime, nullable=False, index=True)
    occupied_seconds = Column(Integer, default=0, nullable=False)
    charged_seconds = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    member = relationship("User")
    member_visit = relationship("MemberVisit", back_populates="table_time_log", uselist=False)
