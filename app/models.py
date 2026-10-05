from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(150), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    chips = Column(Integer, default=1000, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class RoomRecord(Base):
    __tablename__ = "rooms"

    id = Column(Integer, primary_key=True, index=True)
    room_id = Column(String(64), unique=True, index=True, nullable=False)
    name = Column(String(100), nullable=False)
    owner_id = Column(Integer, nullable=False)
    max_players = Column(Integer, default=6, nullable=False)
    small_blind = Column(Integer, default=10, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class HandRecord(Base):
    __tablename__ = "hand_records"
    __table_args__ = (UniqueConstraint("room_id", "hand_number", name="uq_room_hand_number"),)

    id = Column(Integer, primary_key=True, index=True)
    room_id = Column(String(64), index=True, nullable=False)
    hand_number = Column(Integer, nullable=False)
    room_name = Column(String(100), nullable=False)
    small_blind = Column(Integer, nullable=False)
    pot = Column(Integer, nullable=False)
    started_at = Column(Float, nullable=True)
    completed_at = Column(Float, nullable=False)
    duration_seconds = Column(Float, nullable=False, default=0)
    board_json = Column(Text, nullable=False)
    events_json = Column(Text, nullable=False)
    players_json = Column(Text, nullable=False)
    summary_json = Column(Text, nullable=False)


class HandPlayerRecord(Base):
    __tablename__ = "hand_player_records"
    __table_args__ = (UniqueConstraint("hand_id", "user_id", name="uq_hand_player"),)

    id = Column(Integer, primary_key=True, index=True)
    hand_id = Column(Integer, ForeignKey("hand_records.id", ondelete="CASCADE"), index=True, nullable=False)
    user_id = Column(Integer, index=True, nullable=False)
    username = Column(String(50), nullable=False)
    chips_before = Column(Integer, nullable=False)
    chips_after = Column(Integer, nullable=False)
    chips_net = Column(Integer, nullable=False)
    contributed = Column(Integer, nullable=False)
    won = Column(Integer, nullable=False, default=0)
    folded = Column(Integer, nullable=False, default=0)
    hand_label = Column(String(50), nullable=True)
    hole_cards_json = Column(Text, nullable=False)
    actions_json = Column(Text, nullable=False)
