from datetime import date
from fastapi import APIRouter, HTTPException, Depends
from typing import List
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
def get_curriculum(_user=Depends(get_current_user)):
    """전체 커리큘럼 Phase 목록 + 날짜 기반 동적 진행률 반환"""
    supabase = get_supabase()

    phases_res = (
        supabase.table("curriculum")
        .select("*")
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

