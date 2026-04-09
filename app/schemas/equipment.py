from pydantic import BaseModel
from typing import Optional


class EquipmentResponse(BaseModel):
    id: int
    name: str
    serial_no: str
    category: str
    status: str
    borrower_name: Optional[str] = None
    borrower_id: Optional[str] = None
    borrowed_at: Optional[str] = None


class EquipmentBorrowRequest(BaseModel):
    reason: str


class EquipmentActionResponse(BaseModel):
    id: int
    status: str
    message: str
