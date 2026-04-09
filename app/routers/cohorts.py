from typing import List, Optional
from pydantic import BaseModel
from fastapi import APIRouter
from app.utils.supabase_client import get_supabase

router = APIRouter(prefix="/api/cohorts", tags=["cohorts"])


class CohortOption(BaseModel):
    id: str
    name: str
    teacher_name: Optional[str] = None
    is_active: bool = True


class MentorOption(BaseModel):
    id: str   # auth.users.id
    name: str


@router.get("/options", response_model=List[CohortOption])
def get_cohort_options():
    """회원가입 화면용 — 활성 코호트 목록 (인증 불필요)"""
    supabase = get_supabase()

    cohorts_res = (
        supabase.table("cohorts")
        .select("id, name, teacher_id, is_active")
        .eq("is_active", True)
        .order("name")
        .execute()
    )
    cohorts = cohorts_res.data or []

    if not cohorts:
        return []

    # 담당 강사 이름 배치 조회
    teacher_ids = list({c["teacher_id"] for c in cohorts if c.get("teacher_id")})
    teacher_names: dict = {}
    if teacher_ids:
        teachers_res = (
            supabase.table("profiles")
            .select("user_id, name")
            .in_("user_id", teacher_ids)
            .execute()
        )
        teacher_names = {t["user_id"]: t["name"] for t in (teachers_res.data or [])}

    return [
        CohortOption(
            id=str(c["id"]),
            name=c["name"],
            teacher_name=teacher_names.get(c["teacher_id"]) if c.get("teacher_id") else None,
            is_active=c["is_active"],
        )
        for c in cohorts
    ]


@router.get("/mentors", response_model=List[MentorOption])
def get_mentor_options():
    """회원가입 화면용 — 멘토(관리자) 목록 (인증 불필요)"""
    supabase = get_supabase()

    mentors_res = (
        supabase.table("profiles")
        .select("user_id, name")
        .eq("role", "admin")
        .order("name")
        .execute()
    )

    return [
        MentorOption(id=str(m["user_id"]), name=m["name"])
        for m in (mentors_res.data or [])
    ]
