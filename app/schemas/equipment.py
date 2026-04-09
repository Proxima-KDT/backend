from pydantic import BaseModel
from typing import Optional


class EquipmentResponse(BaseModel):
    id: str
    name: str
    serial: str
    category: str
    status: str
    borrower: Optional[str] = None
    borrower_id: Optional[str] = None
    borrowed_date: Optional[str] = None


class EquipmentBorrowRequest(BaseModel):
    reason: str


class EquipmentActionResponse(BaseModel):
    id: str
    status: str
    message: str
