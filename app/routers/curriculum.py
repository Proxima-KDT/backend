from fastapi import APIRouter, HTTPException, Depends
from typing import List
from app.dependencies import get_current_user
from app.utils.supabase_client import get_supabase
from app.schemas.curriculum import CurriculumPhaseResponse, PhaseTaskItem

router = APIRouter(prefix="/api/curriculum", tags=["curriculum"])


@router.get("", response_model=List[CurriculumPhaseResponse])
def get_curriculum(_user=Depends(get_current_user)):
    """전체 커리큘럼 Phase 목록 + 태스크 진행률 반환"""
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
        tasks_data = phase.get("tasks") or []
        tasks = []
        for t in tasks_data:
            if isinstance(t, dict):
                tasks.append(PhaseTaskItem(
                    name=t.get("name", ""),
                    progress=t.get("progress", 0),
                ))

        if tasks:
            avg_progress = sum(t.progress for t in tasks) // len(tasks)
        else:
            avg_progress = phase.get("progress", 0)

        result.append(
            CurriculumPhaseResponse(
                id=phase["id"],
                phase=phase["phase"],
                title=phase["title"],
                description=phase.get("description"),
                icon=phase.get("icon"),
                start_date=str(phase["start_date"]) if phase.get("start_date") else None,
                end_date=str(phase["end_date"]) if phase.get("end_date") else None,
                status=phase["status"],
                progress=avg_progress,
                tasks=tasks,
                tags=phase.get("tags") or [],
            )
        )
    return result


@router.get("/{phase_id}/tasks", response_model=List[PhaseTaskItem])
def get_phase_tasks(phase_id: int, _user=Depends(get_current_user)):
    """특정 Phase의 태스크 목록 반환 (JSONB에서 추출)"""
    supabase = get_supabase()

    phase_res = (
        supabase.table("curriculum")
        .select("id, tasks")
        .eq("id", phase_id)
        .execute()
    )
    if not phase_res.data:
        raise HTTPException(status_code=404, detail="커리큘럼 Phase를 찾을 수 없습니다.")

    tasks_data = phase_res.data[0].get("tasks") or []
    return [
        PhaseTaskItem(name=t.get("name", ""), progress=t.get("progress", 0))
        for t in tasks_data
        if isinstance(t, dict)
    ]

