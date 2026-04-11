from pydantic import BaseModel
from typing import List, Optional


class ProfileResponse(BaseModel):
    id: str
    name: str
    email: Optional[str]
    avatar_url: Optional[str]
    role: str
    target_jobs: List[str] = []
    overall_score: int = 0
    tier: str = "Beginner"
    course_name: Optional[str] = None
    cohort_number: Optional[int] = None
    course_start_date: Optional[str] = None
    course_end_date: Optional[str] = None


class ProfileUpdateTargetJobs(BaseModel):
    jobs: List[str]


class SkillScoreResponse(BaseModel):
    attendance: int = 0
    ai_speaking: int = 0
    ai_interview: int = 0
    portfolio: int = 0
    project_assignment_exam: int = 0
    overall_score: int = 0
    tier: str = "Beginner"
