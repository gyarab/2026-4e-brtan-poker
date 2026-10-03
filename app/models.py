from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(150), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    chips = Column(Integer, default=1000, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class RoomRecord(Base):
    __tablename__ = "rooms"

    id = Column(Integer, primary_key=True, index=True)
    room_id = Column(String(64), unique=True, index=True, nullable=False)
    name = Column(String(100), nullable=False)
    owner_id = Column(Integer, nullable=False)
    max_players = Column(Integer, default=6, nullable=False)
    small_blind = Column(Integer, default=10, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
