from datetime import date
from fastapi import APIRouter, HTTPException, Depends, Query
from typing import List, Optional
from app.dependencies import get_current_user
from app.utils.supabase_client import get_supabase
from app.schemas.curriculum import CurriculumPhaseResponse, PhaseTaskItem

router = APIRouter(prefix="/api/curriculum", tags=["curriculum"])


def _compute_phase(phase: dict) -> tuple:
    """날짜 기반으로 status, progress, tasks 를 동적 계산한다."""
    today = date.today()
    try:
        start = date.fromisoformat(str(phase.get("start_date", "")))
        end = date.fromisoformat(str(phase.get("end_date", "")))
    except (ValueError, TypeError):
        return "upcoming", 0, []

    if today > end:
        status, overall = "completed", 100
    elif today >= start:
        status = "in_progress"
        total_days = max((end - start).days, 1)
        elapsed = (today - start).days
        overall = min(100, max(0, int(elapsed / total_days * 100)))
    else:
        status, overall = "upcoming", 0

    # 태스크 진행률: 각 태스크가 phase 기간을 균등 분할
    tasks_data = phase.get("tasks") or []
    tasks = []
    n = len(tasks_data)
    if n > 0:
        total_days = max((end - start).days, 1)
        elapsed = (today - start).days if status != "upcoming" else 0
        if status == "completed":
            elapsed = total_days
        days_per_task = total_days / n

        for i, t in enumerate(tasks_data):
            if not isinstance(t, dict):
                continue
            task_start = i * days_per_task
            task_end = (i + 1) * days_per_task
            if elapsed >= task_end:
                tp = 100
            elif elapsed > task_start:
                tp = int(((elapsed - task_start) / days_per_task) * 100)
            else:
                tp = 0
            tasks.append(PhaseTaskItem(name=t.get("name", ""), progress=tp))

    return status, overall, tasks


@router.get("", response_model=List[CurriculumPhaseResponse])
def get_curriculum(
    user=Depends(get_current_user),
    course_id: Optional[str] = Query(None),
):
    """커리큘럼 반환.
    - course_id 쿼리 파라미터가 있으면 해당 과정 커리큘럼 반환 (강사용).
    - 없으면 로그인한 학생의 수강 과정 커리큘럼 반환."""
    supabase = get_supabase()

    if not course_id:
        # 학생의 course_id 조회 (강사/관리자는 NULL → 빈 배열)
        me = (
            supabase.table("users")
            .select("course_id")
            .eq("id", user["id"])
            .limit(1)
            .execute()
        )
        course_id = (me.data[0].get("course_id") if me.data else None)
        if not course_id:
            return []

    phases_res = (
        supabase.table("curriculum")
        .select("*")
        .eq("course_id", course_id)
        .order("phase")
        .execute()
    )
    phases = phases_res.data or []

    result = []
    for phase in phases:
        status, progress, tasks = _compute_phase(phase)

        result.append(
            CurriculumPhaseResponse(
                id=phase["id"],
                phase=phase["phase"],
                title=phase["title"],
                description=phase.get("description"),
                icon=phase.get("icon"),
                start_date=str(phase["start_date"]) if phase.get("start_date") else None,
                end_date=str(phase["end_date"]) if phase.get("end_date") else None,
                status=status,
                progress=progress,
                tasks=tasks,
                tags=phase.get("tags") or [],
            )
        )
    return result


@router.get("/course-period", response_model=dict)
def get_course_period(
    user=Depends(get_current_user),
    course_id: Optional[str] = Query(None),
):
    """수강 과정 기간 반환 (과정명 + 기수 날짜).
    - course_id 쿼리 파라미터가 있으면 해당 과정 정보 반환 (강사용).
    - 없으면 로그인한 학생의 수강 과정 정보 반환."""
    from app.utils.supabase_client import reset_supabase

    def _fetch(sb):
        cohort_id = None
        cid = course_id

        if not cid:
            user_res = (
                sb.table("users")
                .select("course_id, cohort_id")
                .eq("id", user["id"])
                .limit(1)
                .execute()
            )
            if not user_res.data:
                return {}
            row = user_res.data[0]
            cid = row.get("course_id")
            cohort_id = row.get("cohort_id")
            if not cid:
                return {}

        course_res = (
            sb.table("courses")
            .select("name,track_type,classroom,duration_months")
            .eq("id", cid)
            .limit(1)
            .execute()
        )
        course = course_res.data[0] if course_res.data else {}

        start_date = end_date = cohort_number = None
        if cohort_id:
            cohort_res = (
                sb.table("cohorts")
                .select("cohort_number,start_date,end_date")
                .eq("id", cohort_id)
                .limit(1)
                .execute()
            )
            if cohort_res.data:
                c = cohort_res.data[0]
                cohort_number = c.get("cohort_number")
                start_date = c.get("start_date")
                end_date = c.get("end_date")

        return {
            "course_id": cid,
            "course_name": course.get("name"),
            "track_type": course.get("track_type"),
            "classroom": course.get("classroom"),
            "duration_months": course.get("duration_months"),
            "cohort_number": cohort_number,
            "start_date": start_date,
            "end_date": end_date,
        }

    supabase = get_supabase()
    try:
        return _fetch(supabase)
    except Exception:
        # stale connection → 클라이언트 재생성 후 1회 재시도
        supabase = reset_supabase()
        return _fetch(supabase)


@router.get("/{phase_id}/tasks", response_model=List[PhaseTaskItem])
def get_phase_tasks(phase_id: int, _user=Depends(get_current_user)):
    """특정 Phase의 태스크 목록 반환 (날짜 기반 동적 진행률)"""
    supabase = get_supabase()

    phase_res = (
        supabase.table("curriculum")
        .select("*")
        .eq("id", phase_id)
        .execute()
    )
    if not phase_res.data:
        raise HTTPException(status_code=404, detail="커리큘럼 Phase를 찾을 수 없습니다.")

    _, _, tasks = _compute_phase(phase_res.data[0])
    return tasks

