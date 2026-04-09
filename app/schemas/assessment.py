from pydantic import BaseModel
from typing import List, Optional


class RubricItem(BaseModel):
    item: str
    maxScore: int
    score: Optional[int] = None


class AssessmentResponse(BaseModel):
    id: str
    phase_id: Optional[int]
    phase_title: Optional[str]
    subject: Optional[str]
    description: Optional[str]
    status: str
    period: Optional[dict] = None
    requirements: List[str] = []
    coverage_topics: List[str] = []
    rubric: List[RubricItem] = []
    max_score: int = 100
    score: Optional[int] = None
    passed: Optional[bool] = None
    feedback: Optional[str] = None
    submitted_files: List[dict] = []
    submitted_at: Optional[str] = None


class AssessmentSubmitResponse(BaseModel):
    id: str
    status: str
    submitted_at: str
