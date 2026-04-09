from pydantic import BaseModel
from typing import List, Optional


class ProblemResponse(BaseModel):
    id: int
    title: str
    description: Optional[str]
    type: str
    difficulty: Optional[str]
    tags: List[str] = []
    date: Optional[str]
    submitted: bool = False
    score: Optional[int] = None
    choices: Optional[list] = None
    correct_answer: Optional[str] = None


class ProblemSubmitRequest(BaseModel):
    answer: str


class ProblemEvaluationResponse(BaseModel):
    is_correct: bool
    score: int
    feedback: Optional[str] = None
