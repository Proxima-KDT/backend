from pydantic import BaseModel
from typing import List, Optional


class ProfileResponse(BaseModel):
    id: str
    user_id: str
    name: str
    email: Optional[str]
    avatar_url: Optional[str]
    role: str
    target_jobs: List[str] = []
    cohort_id: Optional[str] = None
    cohort_name: Optional[str] = None
    mentor_id: Optional[str] = None
    mentor_name: Optional[str] = None


class ProfileUpdateTargetJobs(BaseModel):
    jobs: List[str]


class SkillScoreResponse(BaseModel):
    subject: str
    score: int
    abbr: Optional[str] = None
    fullMark: int = 100
