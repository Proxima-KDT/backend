from pydantic import BaseModel
from typing import List, Optional


class KeywordStatus(BaseModel):
    word: str
    status: str


class VoiceTopicResponse(BaseModel):
    id: str
    category: str
    difficulty: str
    question: str
    description: Optional[str] = None
    keywords: List[str] = []


class VoiceAnalyzeRequest(BaseModel):
    topic: str
    transcript: str
    keywords: List[str] = []
    topic_id: Optional[str] = None


class VoiceAnalyzeResponse(BaseModel):
    score: int
    total_keywords: int
    correct: int
    inaccurate: int
    missing: int
    feedback: str
    tip: Optional[str] = None
    keywords: List[KeywordStatus] = []


class VoiceHistoryResponse(BaseModel):
    id: str
    date: str
    time: Optional[str]
    topic: str
    duration: Optional[str]
    score: int
    correct: int
    inaccurate: int
    missing: int
    feedback: Optional[str]
    tip: Optional[str] = None
    transcript: Optional[str]
    keywords: List[KeywordStatus] = []
