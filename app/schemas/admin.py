import re
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Dict

# RFC 2606 예약 TLD(.test 등)도 허용하는 단순 이메일 검증.
# 엄격한 MX 체크는 Supabase Auth가 담당한다.
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _normalize_email(v: str) -> str:
    v = (v or "").strip().lower()
    if not _EMAIL_RE.match(v):
        raise ValueError("올바른 이메일 형식이 아닙니다.")
    return v


# ── 과정(course) & 기수(cohort) ─────────────────────

class CohortResponse(BaseModel):
    id: int
    cohort_number: int
    status: str  # upcoming | in_progress | completed
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    student_count: int = 0


class CourseResponse(BaseModel):
    id: str
    name: str
    track_type: str  # main | sub
    classroom: str
    duration_months: int
    daily_start_time: str
    daily_end_time: str
    description: Optional[str] = None
    cohorts: List[CohortResponse] = []
    student_count: int = 0
    teacher_id: Optional[str] = None
    teacher_name: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None


# ── 학생/강사 관리 (관리자) ────────────────────────

class CreateStudentRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=6, max_length=72)
    address: Optional[str] = None
    phone: Optional[str] = None
    course_id: str = Field(min_length=1, max_length=50)
    cohort_id: Optional[int] = None  # 메인 과정일 때만 필수 (서비스에서 검증)

    @field_validator("email")
    @classmethod
    def _v_email(cls, v: str) -> str:
        return _normalize_email(v)


class CreateTeacherRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=6, max_length=72)
    address: Optional[str] = None
    phone: Optional[str] = None
    course_ids: List[str] = Field(default_factory=list)

    @field_validator("email")
    @classmethod
    def _v_email(cls, v: str) -> str:
        return _normalize_email(v)


class CreateUserResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str
    address: Optional[str] = None
    phone: Optional[str] = None
    course_id: Optional[str] = None
    cohort_id: Optional[int] = None
    course_ids: Optional[List[str]] = None  # teacher 전용


class UpdateUserPasswordRequest(BaseModel):
    new_password: str = Field(min_length=6, max_length=72)


class AdminStudentResponse(BaseModel):
    id: str
    name: str
    email: Optional[str] = None
    avatar_url: Optional[str] = None
    role: str = "student"
    attendance_rate: float = 0
    submission_rate: float = 0
    is_at_risk: bool = False
    last_active: Optional[str] = None
    enrolled_at: Optional[str] = None
    skills: Dict[str, float] = {}
    files: List[dict] = []
    # 과정/기수 정보
    address: Optional[str] = None
    phone: Optional[str] = None
    course_id: Optional[str] = None
    course_name: Optional[str] = None
    cohort_id: Optional[int] = None
    cohort_number: Optional[int] = None


class UserRoleUpdateRequest(BaseModel):
    new_role: str  # student, teacher, admin


# ── 장비 관리 ─────────────────────────────────────

class AdminEquipmentResponse(BaseModel):
    id: str
    name: str
    serial_no: str
    category: Optional[str] = None
    status: str
    borrower: Optional[str] = None
    borrower_id: Optional[str] = None
    borrowed_at: Optional[str] = None
    image_url: Optional[str] = None


class EquipmentCreateRequest(BaseModel):
    name: str
    serial_no: str
    category: Optional[str] = None
    image_url: Optional[str] = None


class EquipmentUpdateRequest(BaseModel):
    name: Optional[str] = None
    serial_no: Optional[str] = None
    category: Optional[str] = None
    image_url: Optional[str] = None


class EquipmentStatusUpdate(BaseModel):
    status: str  # available, maintenance, retired


class EquipmentRequestResponse(BaseModel):
    id: str
    student_name: Optional[str] = None
    equipment_name: Optional[str] = None
    request_date: Optional[str] = None
    reason: Optional[str] = None
    status: str


class EquipmentRejectRequest(BaseModel):
    reason: str


class EquipmentHistoryItem(BaseModel):
    id: str
    date: Optional[str] = None
    action: Optional[str] = None
    user_name: Optional[str] = None
    note: Optional[str] = None


class EquipmentSession(BaseModel):
    """대여·반납을 하나의 세션으로 묶은 응답"""
    user_name: Optional[str] = None
    borrow_at: Optional[str] = None   # ISO datetime — 대여 시각
    return_at: Optional[str] = None   # ISO datetime — 반납 시각 (None = 대여중)
    is_active: bool = False            # 현재 대여 중 (반납 로그 없음)
    note: Optional[str] = None
    action: str = "borrow"            # borrow | maintenance | status_change


# ── 시설 예약 관리 ─────────────────────────────────

class AdminRoomResponse(BaseModel):
    id: str
    name: str
    type: str
    capacity: int = 0
    floor: Optional[int] = None
    amenities: List[str] = []
    status: str = "open"


class RoomCreateRequest(BaseModel):
    name: str
    type: str  # study, meeting
    capacity: int = 0
    floor: Optional[int] = None
    amenities: List[str] = []


class RoomUpdateRequest(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    capacity: Optional[int] = None
    floor: Optional[int] = None
    amenities: Optional[List[str]] = None


class RoomStatusUpdate(BaseModel):
    status: str  # open, closed


class AdminBookedSlotResponse(BaseModel):
    id: str
    room_id: str
    date: str
    start_time: str
    end_time: str
    reserved_by: Optional[str] = None
    purpose: Optional[str] = None
    user_id: Optional[str] = None



# ── 강의(Course) / 기수(Cohort) CRUD ────────────────

class CreateCourseRequest(BaseModel):
    id: str = Field(min_length=1, max_length=50)   # 예: course-newcourse
    name: str = Field(min_length=1, max_length=100)
    track_type: str = "main"                        # main | sub
    classroom: str = Field(min_length=1, max_length=100)
    duration_months: int = Field(ge=1, le=24)
    daily_start_time: str                           # HH:MM
    daily_end_time: str
    description: Optional[str] = None
    teacher_id: Optional[str] = None               # 담당 강사 UUID
    start_date: Optional[str] = None               # YYYY-MM-DD (서브 과정 운영 기간)
    end_date: Optional[str] = None


class UpdateCourseRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    track_type: Optional[str] = None
    classroom: Optional[str] = None
    duration_months: Optional[int] = Field(None, ge=1, le=24)
    daily_start_time: Optional[str] = None
    daily_end_time: Optional[str] = None
    description: Optional[str] = None
    teacher_id: Optional[str] = None               # None = 변경 없음, "" = 배정 해제
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class CreateCohortRequest(BaseModel):
    cohort_number: int = Field(ge=1)
    status: str = "upcoming"                        # upcoming | in_progress | completed
    start_date: Optional[str] = None               # YYYY-MM-DD
    end_date: Optional[str] = None


class UpdateCohortRequest(BaseModel):
    cohort_number: Optional[int] = Field(None, ge=1)
    status: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
