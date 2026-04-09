from pydantic import BaseModel
from typing import List, Optional, Dict


# ── 학생 관리 (관리자) ────────────────────────────

class AdminStudentResponse(BaseModel):
    id: str
    name: str
    email: Optional[str] = None
    avatar_url: Optional[str] = None
    role: str = "student"
    attendance_rate: float = 0
    submission_rate: float = 0
    is_at_risk: bool = False
    last_active: Optional[str] = None
    enrolled_at: Optional[str] = None
    skills: Dict[str, float] = {}
    files: List[dict] = []


class UserRoleUpdateRequest(BaseModel):
    new_role: str  # student, teacher, admin


# ── 장비 관리 ─────────────────────────────────────

class AdminEquipmentResponse(BaseModel):
    id: str
    name: str
    serial_no: str
    category: Optional[str] = None
    status: str
    borrower: Optional[str] = None
    borrower_id: Optional[str] = None
    borrowed_at: Optional[str] = None


class EquipmentCreateRequest(BaseModel):
    name: str
    serial_no: str
    category: Optional[str] = None


class EquipmentStatusUpdate(BaseModel):
    status: str  # available, maintenance, retired


class EquipmentRequestResponse(BaseModel):
    id: str
    student_name: Optional[str] = None
    equipment_name: Optional[str] = None
    request_date: Optional[str] = None
    reason: Optional[str] = None
    status: str


class EquipmentRejectRequest(BaseModel):
    reason: str


class EquipmentHistoryItem(BaseModel):
    id: str
    date: Optional[str] = None
    action: Optional[str] = None
    user_name: Optional[str] = None
    note: Optional[str] = None


# ── 시설 예약 관리 ─────────────────────────────────

class AdminRoomResponse(BaseModel):
    id: str
    name: str
    type: str
    capacity: int = 0
    floor: Optional[int] = None
    amenities: List[str] = []
    status: str = "open"


class RoomCreateRequest(BaseModel):
    name: str
    type: str  # study, meeting
    capacity: int = 0
    floor: Optional[int] = None
    amenities: List[str] = []


class RoomUpdateRequest(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    capacity: Optional[int] = None
    floor: Optional[int] = None
    amenities: Optional[List[str]] = None


class RoomStatusUpdate(BaseModel):
    status: str  # open, closed


class AdminBookedSlotResponse(BaseModel):
    id: str
    room_id: str
    date: str
    start_time: str
    end_time: str
    reserved_by: Optional[str] = None
    purpose: Optional[str] = None
    user_id: Optional[str] = None
