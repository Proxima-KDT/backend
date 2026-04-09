from pydantic import BaseModel
from typing import List, Optional


class ProblemResponse(BaseModel):
    id: str
    title: Optional[str]
    question: Optional[str]
    type: str
    difficulty: Optional[str]
    tags: List[str] = []
    date: Optional[str]
    submitted: bool = False
    score: Optional[int] = None
    choices: Optional[list] = None
    answer: Optional[int] = None


class ProblemSubmitRequest(BaseModel):
    answer: str


class ProblemEvaluationResponse(BaseModel):
    is_correct: bool
    score: int
    feedback: Optional[str] = None
