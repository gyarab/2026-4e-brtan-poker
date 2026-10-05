from typing import Any, Dict, List, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator


class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=6)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("Username must contain at least 3 non-space characters")
        return value

    @field_validator("password")
    @classmethod
    def enforce_bcrypt_byte_limit(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password must be at most 72 UTF-8 bytes")
        return value


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    username: str
    email: str
    chips: int


class RoomCreate(BaseModel):
    name: str = Field(..., min_length=3, max_length=100)
    max_players: int = Field(6, ge=2, le=9)
    small_blind: int = Field(10, ge=1, le=1000)

    @field_validator("name")
    @classmethod
    def normalize_room_name(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("Room name must contain at least 3 non-space characters")
        return value


class RoomJoinRequest(BaseModel):
    room_id: str


class ActionPayload(BaseModel):
    room_id: str
    action: str
    amount: Optional[int] = None


class RoomStatePublic(BaseModel):
    room_id: str
    name: str
    owner_id: int
    max_players: int
    small_blind: int
    phase: str
    players: List[Dict[str, Any]]
    board: List[str]
    pot: int
    current_turn: Optional[int]
    history: List[str]
