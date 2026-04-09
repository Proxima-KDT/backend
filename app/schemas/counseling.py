from pydantic import BaseModel
from typing import Optional, List


class CounselorResponse(BaseModel):
    id: str
    name: str
    role: Optional[str] = None
    role_label: Optional[str] = None


class CounselingSlotResponse(BaseModel):
    date: str
    available_times: List[str]
    blocked_times: List[str]


class CounselingBookRequest(BaseModel):
    counselor_id: str
    date: str
    time: str
    reason: Optional[str] = None


class CounselingBookingResponse(BaseModel):
    id: str
    counselor_id: str
    counselor_name: Optional[str] = None
    counselor_role: Optional[str] = None
    counselor_role_label: Optional[str] = None
    student_id: Optional[str] = None
    student_name: Optional[str] = None
    date: str
    time: str
    duration: int = 30
    reason: Optional[str] = None
    status: str
