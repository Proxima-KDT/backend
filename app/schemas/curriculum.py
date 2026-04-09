from pydantic import BaseModel
from typing import List, Optional


class PhaseTaskItem(BaseModel):
    name: str
    progress: int = 0


class CurriculumPhaseResponse(BaseModel):
    id: int
    phase: int
    title: str
    description: Optional[str]
    icon: Optional[str]
    start_date: Optional[str]
    end_date: Optional[str]
    status: str
    progress: int = 0
    tasks: List[PhaseTaskItem] = []
    tags: List[str] = []
