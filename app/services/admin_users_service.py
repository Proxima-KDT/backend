"""관리자 전용 — 학생/강사 계정 생성 및 과정/기수 관리 로직.

Supabase Auth admin API로 사용자를 직접 생성한 뒤,
`handle_new_user` 트리거가 public.users 기본 행을 만들면
course_id/cohort_id/address/phone 등 부가 정보를 업데이트한다.
"""
from typing import List, Optional
from fastapi import HTTPException, status
from app.utils.supabase_client import get_supabase


# ─────────────────────────────────────────────
# Supabase Auth helpers
# ─────────────────────────────────────────────

def _create_auth_user(email: str, password: str, name: str, role: str) -> str:
    """Supabase Auth에 사용자 생성. 생성된 user id(uuid) 반환."""
    supabase = get_supabase()
    try:
        res = supabase.auth.admin.create_user(
            {
                "email": email,
                "password": password,
                "email_confirm": True,  # 관리자 생성 계정은 즉시 활성화
                "user_metadata": {"name": name, "role": role},
            }
        )
    except Exception as e:
        msg = str(e)
        if "already" in msg.lower() or "registered" in msg.lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="이미 등록된 이메일입니다.",
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"계정 생성 실패: {msg}",
        )

    user_obj = getattr(res, "user", None)
    if not user_obj or not getattr(user_obj, "id", None):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Supabase가 사용자 ID를 반환하지 않았습니다.",
        )
    return user_obj.id


def _ensure_users_row(user_id: str, email: str, name: str, role: str) -> None:
    """handle_new_user 트리거가 동작했는지 확인하고, 없다면 upsert로 보정."""
    supabase = get_supabase()
    existing = (
        supabase.table("users").select("id").eq("id", user_id).limit(1).execute()
    )
    if existing.data:
        # 이름/role은 최신값으로 동기화
        supabase.table("users").update(
            {"name": name, "role": role}
        ).eq("id", user_id).execute()
        return
    supabase.table("users").insert(
        {"id": user_id, "email": email, "name": name, "role": role}
    ).execute()


def _rollback_auth_user(user_id: str) -> None:
    """중간 실패 시 auth 계정을 삭제해 고아 상태를 방지한다."""
    try:
        get_supabase().auth.admin.delete_user(user_id)
    except Exception:
        pass  # 롤백 실패는 삼킨다 (원본 오류를 노출하기 위해)


# ─────────────────────────────────────────────
# Course / Cohort 조회
# ─────────────────────────────────────────────

def list_courses() -> List[dict]:
    """courses 전체를 cohorts와 함께 반환한다."""
    supabase = get_supabase()
    courses = (
        supabase.table("courses")
        .select("id,name,track_type,classroom,duration_months,daily_start_time,daily_end_time,description")
        .order("track_type")
        .order("name")
        .execute()
        .data or []
    )
    cohorts = (
        supabase.table("cohorts")
        .select("id,course_id,cohort_number,status,start_date,end_date")
        .order("cohort_number")
        .execute()
        .data or []
    )

    by_course: dict = {}
    for c in cohorts:
        by_course.setdefault(c["course_id"], []).append(
            {
                "id": c["id"],
                "cohort_number": c["cohort_number"],
                "status": c["status"],
                "start_date": c.get("start_date"),
                "end_date": c.get("end_date"),
            }
        )

    result = []
    for course in courses:
        result.append(
            {
                "id": course["id"],
                "name": course["name"],
                "track_type": course["track_type"],
                "classroom": course["classroom"],
                "duration_months": course["duration_months"],
                "daily_start_time": str(course["daily_start_time"])[:5],
                "daily_end_time": str(course["daily_end_time"])[:5],
                "description": course.get("description"),
                "cohorts": by_course.get(course["id"], []),
            }
        )
    return result


def _get_course_or_400(course_id: str) -> dict:
    supabase = get_supabase()
    res = (
        supabase.table("courses")
        .select("id,track_type")
        .eq("id", course_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="존재하지 않는 과정입니다.",
        )
    return res.data[0]


# ─────────────────────────────────────────────
# 학생 생성
# ─────────────────────────────────────────────

def create_student(
    email: str,
    password: str,
    name: str,
    course_id: str,
    cohort_id: Optional[int] = None,
    address: Optional[str] = None,
    phone: Optional[str] = None,
) -> dict:
    supabase = get_supabase()

    # 1) 과정 검증
    course = _get_course_or_400(course_id)
    track = course["track_type"]

    # 2) 기수 검증 (메인 과정만 허용)
    effective_cohort_id: Optional[int] = None
    if track == "main":
        if cohort_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="메인 과정은 기수를 선택해야 합니다.",
            )
        cohort_res = (
            supabase.table("cohorts")
            .select("id,course_id,status")
            .eq("id", cohort_id)
            .limit(1)
            .execute()
        )
        if not cohort_res.data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="존재하지 않는 기수입니다.",
            )
        cohort_row = cohort_res.data[0]
        if cohort_row["course_id"] != course_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="선택한 기수가 해당 과정에 속하지 않습니다.",
            )
        # 신규 학생은 "예정(upcoming)" 기수에만 등록 가능.
        # 진행중 기수는 중도 합류 방지, 수료 기수는 소급 등록 방지.
        if cohort_row.get("status") != "upcoming":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="예정된 기수에만 학생을 등록할 수 있습니다. 현재 진행중이거나 종료된 기수는 선택할 수 없습니다.",
            )
        effective_cohort_id = cohort_id
    else:
        # 서브 과정은 기수 무시
        effective_cohort_id = None

    # 3) 계정 생성
    user_id = _create_auth_user(email, password, name, "student")
    try:
        _ensure_users_row(user_id, email, name, "student")
        supabase.table("users").update(
            {
                "address": address,
                "phone": phone,
                "course_id": course_id,
                "cohort_id": effective_cohort_id,
            }
        ).eq("id", user_id).execute()
    except Exception as e:
        _rollback_auth_user(user_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"학생 정보 저장 실패: {e}",
        )

    return {
        "id": user_id,
        "email": email,
        "name": name,
        "role": "student",
        "address": address,
        "phone": phone,
        "course_id": course_id,
        "cohort_id": effective_cohort_id,
    }


# ─────────────────────────────────────────────
# 강사 생성
# ─────────────────────────────────────────────

def create_teacher(
    email: str,
    password: str,
    name: str,
    course_ids: List[str],
    address: Optional[str] = None,
    phone: Optional[str] = None,
) -> dict:
    supabase = get_supabase()

    # 1) 모든 course_id가 존재하는지 검증
    course_ids = list(dict.fromkeys(course_ids or []))  # dedupe 유지
    if course_ids:
        existing = (
            supabase.table("courses")
            .select("id")
            .in_("id", course_ids)
            .execute()
            .data or []
        )
        existing_ids = {c["id"] for c in existing}
        missing = [cid for cid in course_ids if cid not in existing_ids]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"존재하지 않는 과정: {', '.join(missing)}",
            )

    # 2) 계정 생성
    user_id = _create_auth_user(email, password, name, "teacher")
    try:
        _ensure_users_row(user_id, email, name, "teacher")
        supabase.table("users").update(
            {"address": address, "phone": phone}
        ).eq("id", user_id).execute()

        if course_ids:
            rows = [{"teacher_id": user_id, "course_id": cid} for cid in course_ids]
            supabase.table("teacher_courses").insert(rows).execute()
    except Exception as e:
        _rollback_auth_user(user_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"강사 정보 저장 실패: {e}",
        )

    return {
        "id": user_id,
        "email": email,
        "name": name,
        "role": "teacher",
        "address": address,
        "phone": phone,
        "course_ids": course_ids,
    }


# ─────────────────────────────────────────────
# 비밀번호 재발급
# ─────────────────────────────────────────────

def update_user_password(user_id: str, new_password: str) -> None:
    """Supabase Auth admin API로 비밀번호를 재설정한다."""
    supabase = get_supabase()
    try:
        supabase.auth.admin.update_user_by_id(
            user_id, {"password": new_password}
        )
    except Exception as e:
        msg = str(e)
        if "not found" in msg.lower() or "user_not_found" in msg.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="해당 사용자를 찾을 수 없습니다.",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"비밀번호 변경 실패: {msg}",
        )
