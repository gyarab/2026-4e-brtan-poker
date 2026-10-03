from typing import Any, Dict, List, Optional

from pydantic import BaseModel, EmailStr, Field


class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=6)


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
