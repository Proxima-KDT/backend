from pydantic import BaseModel
from typing import Optional


class CheckInRequest(BaseModel):
    signature_url: Optional[str] = None


class AttendanceRecordResponse(BaseModel):
    date: str
    status: Optional[str]
    time: Optional[str]
    check_out_time: Optional[str] = None


class AttendanceMonthlyResponse(BaseModel):
    year: int
    month: int
    total_days: int
    present: int
    late: int
    absent: int
    rate: float
    records: list = []
