from pydantic import BaseModel
from typing import List, Optional


class RoomResponse(BaseModel):
    id: str
    name: str
    type: str
    status: str
    capacity: int
    amenities: List[str] = []


class BookedSlotResponse(BaseModel):
    room_id: str
    date: str
    start_time: str
    end_time: str
    reserved_by: Optional[str]
    is_mine: bool = False
    purpose: Optional[str]


class ReservationCreateRequest(BaseModel):
    room_id: str
    date: str
    start_time: str
    end_time: str
    purpose: Optional[str] = None


class ReservationResponse(BaseModel):
    id: str
    room_id: str
    room_name: Optional[str]
    room_type: Optional[str]
    date: str
    start_time: str
    end_time: str
    purpose: Optional[str]
    status: str
