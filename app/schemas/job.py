from pydantic import BaseModel
from typing import List, Optional


class JobResponse(BaseModel):
    id: str
    company: str
    position: str
    tech_stack: List[str] = []
    location: Optional[str]
    deadline: Optional[str]
    experience: Optional[str]
    match_score: int = 0
