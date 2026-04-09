from pydantic import BaseModel
from typing import Optional


class SkillScoreResponse(BaseModel):
    category: str
    score: int


class SkillScoreUpdateRequest(BaseModel):
    category: str
    score: int
