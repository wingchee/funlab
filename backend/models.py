from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, func
from sqlalchemy.orm import relationship
from database import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    name = Column(String, nullable=False)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
    favorites = relationship("Favorite", back_populates="user", cascade="all, delete-orphan")


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
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
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
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
