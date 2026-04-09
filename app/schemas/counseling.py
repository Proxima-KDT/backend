from pydantic import BaseModel
from typing import Optional


class CounselorResponse(BaseModel):
    id: str
    name: str
    role: Optional[str]
    role_label: Optional[str]


class CounselingSlotResponse(BaseModel):
    date: str
    times: list


class CounselingBookRequest(BaseModel):
    counselor_id: str
    date: str
    time: str
    reason: Optional[str] = None


class CounselingBookingResponse(BaseModel):
    id: str
    counselor_id: str
    counselor_name: Optional[str]
    counselor_role_label: Optional[str]
    date: str
    time: str
    duration: int = 30
    reason: Optional[str]
    status: str
