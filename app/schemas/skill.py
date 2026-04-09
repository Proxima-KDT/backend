from pydantic import BaseModel
from typing import Optional


class SkillScoreResponse(BaseModel):
    attendance: int = 0
    ai_speaking: int = 0
    ai_interview: int = 0
    portfolio: int = 0
    project_assignment_exam: int = 0
    overall_score: int = 0
    tier: str = "Beginner"


class SkillScoreUpdateRequest(BaseModel):
    attendance: Optional[int] = None
    ai_speaking: Optional[int] = None
    ai_interview: Optional[int] = None
    portfolio: Optional[int] = None
    project_assignment_exam: Optional[int] = None
