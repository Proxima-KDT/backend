from pydantic import BaseModel
from typing import List, Optional


class SubmissionResponse(BaseModel):
    id: str
    problem_id: int
    answer: Optional[str]
    is_correct: Optional[bool]
    score: Optional[int]
    feedback: Optional[str]
    submitted_at: str


class QuizSubmitRequest(BaseModel):
    concept_id: str
    answers: List[dict]


class QuizResultResponse(BaseModel):
    id: str
    concept_id: str
    total_problems: int
    correct_count: int
    score: int
    details: Optional[list] = None
