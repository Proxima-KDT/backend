from pydantic import BaseModel
from typing import List, Optional


class CounselingBookingResponse(BaseModel):
    id: str
    student_id: Optional[str] = None
    student_name: Optional[str] = None
    date: str
    time: str
    duration: Optional[int] = 30
    reason: Optional[str] = None
    status: str


class BookingActionRequest(BaseModel):
    action: str  # confirm, cancel
    reason: Optional[str] = None


class BlockedSlotsUpdate(BaseModel):
    blocked_times: List[str]  # ["09:00", "09:30", ...]
