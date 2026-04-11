from pydantic import BaseModel
from typing import Optional


class QuestionCreateRequest(BaseModel):
    content: str
    is_anonymous: bool = False


class QuestionResponse(BaseModel):
    id: str
    user_id: str
    content: str
    is_anonymous: bool
    author: Optional[str] = None
    course_name: Optional[str] = None
    created_at: str
    answer: Optional[str] = None
    answered_at: Optional[str] = None
