from pydantic import BaseModel
from typing import Optional


class CheckInRequest(BaseModel):
    signature_url: Optional[str] = None


class CheckOutRequest(BaseModel):
    pass


class EarlyLeaveRequest(BaseModel):
    reason: str


class AttendanceRecordResponse(BaseModel):
    date: str
    status: Optional[str]
    time: Optional[str]


class AttendanceMonthlyResponse(BaseModel):
    year: int
    month: int
    total_days: int
    present: int
    late: int
    absent: int
    early_leave: int = 0
    rate: float
    records: list = []
