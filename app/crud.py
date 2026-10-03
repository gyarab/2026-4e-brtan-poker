from sqlalchemy.orm import Session

from app.models import RoomRecord, User
from app.security import get_password_hash


def create_user(db: Session, username: str, email: str, password: str) -> User:
    user = User(
        username=username,
        email=email,
        password_hash=get_password_hash(password),
        chips=1000,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.query(User).filter(User.email == email).first()


def get_user_by_username(db: Session, username: str) -> User | None:
    return db.query(User).filter(User.username == username).first()


def get_user_by_id(db: Session, user_id: int) -> User | None:
    return db.query(User).filter(User.id == user_id).first()


def create_room_record(db: Session, room_id: str, name: str, owner_id: int, max_players: int, small_blind: int) -> RoomRecord:
    room = RoomRecord(
        room_id=room_id,
        name=name,
        owner_id=owner_id,
        max_players=max_players,
        small_blind=small_blind,
    )
    db.add(room)
    db.commit()
    db.refresh(room)
    return room
