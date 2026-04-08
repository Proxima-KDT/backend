from pydantic import BaseModel
from typing import List, Optional


class InterviewStartRequest(BaseModel):
    company: str
    position: str
    interview_type: str  # 'technical' | 'personality' | 'mixed'


class InterviewStartResponse(BaseModel):
    session_id: str
    first_question: str
    total_questions: int


class InterviewAnswerRequest(BaseModel):
    session_id: str
    answer: str


class InterviewAnswerResponse(BaseModel):
    next_question: Optional[str]
    question_number: int
    total_questions: int
    is_finished: bool


class CategoryScore(BaseModel):
    name: str
    score: int


class InterviewReport(BaseModel):
    total_score: int
    categories: List[CategoryScore]
    summary: str
    improvements: List[str]


class InterviewEndRequest(BaseModel):
    session_id: str


class InterviewHistoryItem(BaseModel):
    id: str
    company: str
    position: str
    interview_type: str
    date: str
    score: int
