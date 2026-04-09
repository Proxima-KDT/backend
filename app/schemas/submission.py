from pydantic import BaseModel
from typing import List, Optional


class SubmissionResponse(BaseModel):
    id: int
    problem_id: str
    selected_answer: Optional[int]
    answer_content: Optional[str]
    is_correct: Optional[bool]
    score: Optional[int]
    feedback: Optional[str]
    submitted_at: Optional[str]


class QuizSubmitRequest(BaseModel):
    concept_id: str
    answers: List[dict]


class QuizResultResponse(BaseModel):
    concept_id: str
    total_problems: int
    correct_count: int
    score: int
    details: Optional[list] = None
