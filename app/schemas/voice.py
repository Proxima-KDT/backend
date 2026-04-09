from pydantic import BaseModel
from typing import List, Optional


class KeywordStatus(BaseModel):
    word: str
    status: str


class VoiceAnalyzeRequest(BaseModel):
    topic: str
    transcript: str
    keywords: List[str] = []


class VoiceAnalyzeResponse(BaseModel):
    score: int
    total_keywords: int
    correct: int
    inaccurate: int
    missing: int
    feedback: str
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
    transcript: Optional[str]
    keywords: List[KeywordStatus] = []
