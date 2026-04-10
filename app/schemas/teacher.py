from pydantic import BaseModel
from typing import List, Optional, Dict


# ── 학생 관리 ──────────────────────────────────────

class StudentSkills(BaseModel):
    출결: float = 0
    AI_말하기: float = 0
    AI_면접: float = 0
    포트폴리오: float = 0
    프로젝트_과제_시험: float = 0

    class Config:
        populate_by_name = True


class StudentFile(BaseModel):
    name: str
    type: str
    url: str
    uploaded_at: Optional[str] = None


class TeacherStudentResponse(BaseModel):
    id: str
    name: str
    email: Optional[str] = None
    avatar_url: Optional[str] = None
    attendance_rate: float = 0
    submission_rate: float = 0
    accuracy: float = 0
    is_at_risk: bool = False
    last_active: Optional[str] = None
    enrolled_at: Optional[str] = None
    notes: Optional[str] = None
    skills: Dict[str, float] = {}
    files: List[StudentFile] = []


class StudentNoteUpdate(BaseModel):
    notes: str


class AttendanceWeekRecord(BaseModel):
    date: str
    status: Optional[str] = None
    time: Optional[str] = None


# ── 좌석 & 출결 체크 ──────────────────────────────

class ClassroomSeatResponse(BaseModel):
    seat_id: str
    row: int
    col: int
    student_id: Optional[str] = None
    student_name: Optional[str] = None


class SeatAssignRequest(BaseModel):
    student_id: Optional[str] = None  # None이면 배정 해제


class DailyAttendanceRecord(BaseModel):
    student_id: str
    student_name: str
    seat_id: Optional[str] = None
    status: str
    check_in_time: Optional[str] = None


class AttendanceStatusUpdate(BaseModel):
    status: str  # present, late, absent


# ── 과제 관리 ──────────────────────────────────────

class RubricItem(BaseModel):
    item: str
    maxScore: int


class RubricScoreItem(BaseModel):
    item: str
    score: Optional[int] = None
    maxScore: Optional[int] = None


class FileItem(BaseModel):
    name: str
    size: Optional[str] = None
    url: Optional[str] = None


class StudentSubmission(BaseModel):
    studentId: str
    studentName: str
    status: str = "pending"
    submittedAt: Optional[str] = None
    files: List[FileItem] = []
    score: Optional[int] = None
    feedback: Optional[str] = None
    rubricScores: Optional[List[RubricScoreItem]] = None


class TeacherAssignmentResponse(BaseModel):
    id: str
    title: str
    subject: Optional[str] = None
    phase: Optional[int] = None
    description: Optional[str] = None
    dueDate: Optional[str] = None
    openDate: Optional[str] = None
    maxScore: int = 100
    attachments: List[FileItem] = []
    rubric: List[RubricItem] = []
    studentSubmissions: List[StudentSubmission] = []


class AssignmentCreateRequest(BaseModel):
    title: str
    subject: Optional[str] = None
    phase: Optional[int] = None
    description: Optional[str] = None
    dueDate: Optional[str] = None
    openDate: Optional[str] = None
    maxScore: int = 100
    rubric: List[RubricItem] = []


class GradeSubmissionRequest(BaseModel):
    score: Optional[int] = None
    feedback: Optional[str] = None
    rubricScores: Optional[List[RubricScoreItem]] = None
    status: str = "graded"  # graded or resubmit_required


# ── 평가 관리 ──────────────────────────────────────

class AssessmentSubmission(BaseModel):
    studentId: str
    studentName: str
    status: str = "pending"
    submittedAt: Optional[str] = None
    files: List[FileItem] = []
    score: Optional[int] = None
    passed: Optional[bool] = None
    feedback: Optional[str] = None
    rubricScores: Optional[List[RubricScoreItem]] = None


class TeacherAssessmentResponse(BaseModel):
    id: str
    phaseId: Optional[int] = None
    phaseTitle: Optional[str] = None
    title: Optional[str] = None
    subject: Optional[str] = None
    description: Optional[str] = None
    period: Optional[dict] = None
    maxScore: int = 100
    passScore: int = 60
    rubric: List[RubricItem] = []
    studentSubmissions: List[AssessmentSubmission] = []


class AssessmentGradeRequest(BaseModel):
    score: int
    passed: Optional[bool] = None
    feedback: Optional[str] = None
    rubricScores: Optional[List[RubricScoreItem]] = None


# ── 문제 관리 ──────────────────────────────────────

class ProblemResponse(BaseModel):
    id: str
    title: str
    description: Optional[str] = None
    type: str
    difficulty: Optional[str] = None
    tags: List[str] = []
    choices: Optional[list] = None
    correct_answer: Optional[int] = None
    concept_id: Optional[str] = None
    created_at: Optional[str] = None


class ProblemCreateRequest(BaseModel):
    title: str
    description: Optional[str] = None
    type: str  # multiple_choice, short_answer, code
    difficulty: Optional[str] = None
    tags: List[str] = []
    choices: Optional[list] = None
    correct_answer: Optional[str] = None
    concept_id: Optional[str] = None


class ProblemUpdateRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    type: Optional[str] = None
    difficulty: Optional[str] = None
    tags: Optional[List[str]] = None
    choices: Optional[list] = None
    correct_answer: Optional[str] = None


class AIProblemGenerateRequest(BaseModel):
    topic: str
    difficulty: str = "중"
    count: int = 3
    type: str = "multiple_choice"


# ── 상담 ──────────────────────────────────────────

class CounselingRecordResponse(BaseModel):
    id: str
    student_name: Optional[str] = None
    date: str
    duration: Optional[str] = None
    summary: Optional[str] = None
    action_items: List[str] = []
    speakers: List[str] = []


# ── Q&A ───────────────────────────────────────────

class TeacherQuestionResponse(BaseModel):
    id: str
    user_id: str
    content: str
    is_anonymous: bool
    author: Optional[str] = None
    created_at: str
    answer: Optional[str] = None
    answered_at: Optional[str] = None


class AnswerRequest(BaseModel):
    answer: str
