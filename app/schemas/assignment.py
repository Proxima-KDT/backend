from pydantic import BaseModel
from typing import List, Optional


class AssignmentResponse(BaseModel):
    id: str
    subject: Optional[str]
    title: str
    description: Optional[str]
    status: str
    due_date: Optional[str]
    max_score: int = 100
    score: Optional[int] = None
    rubric: Optional[list] = None
    feedback: Optional[str] = None
    attachments: List[dict] = []
    submitted_files: List[dict] = []
    submitted_at: Optional[str] = None


class AssignmentSubmitResponse(BaseModel):
    id: str
    status: str
    submitted_at: str


class AssignmentFeedbackResponse(BaseModel):
    score: Optional[int]
    feedback: Optional[str]
    rubric: Optional[list]
