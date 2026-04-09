from pydantic import BaseModel
from typing import List, Optional


class QuizProblemResponse(BaseModel):
    id: str
    question: str
    choices: List[str]
    answer: Optional[int] = None
    explanation: Optional[str] = None


class ProgressData(BaseModel):
    solved: int = 0
    total: int = 0
    percent: int = 0


class ConceptResponse(BaseModel):
    id: str
    title: str
    description: Optional[str]
    problems_count: int = 0
    progress: Optional[ProgressData] = None


class ConceptDetailResponse(BaseModel):
    id: str
    title: str
    description: Optional[str]
    problems: List[QuizProblemResponse] = []


class SubjectResponse(BaseModel):
    id: str
    title: str
    description: Optional[str]
    icon: Optional[str]
    color: Optional[str]
    phase: Optional[int]
    concepts: List[ConceptResponse] = []
    progress: Optional[ProgressData] = None


class SubjectProgressResponse(BaseModel):
    subject_id: str
    total_problems: int
    solved_problems: int
    progress: int = 0
