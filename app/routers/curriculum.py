from fastapi import APIRouter, HTTPException, Depends
from typing import List
from app.dependencies import get_current_user
from app.utils.supabase_client import get_supabase
from app.schemas.curriculum import CurriculumPhaseResponse, PhaseTaskResponse

router = APIRouter(prefix="/api/curriculum", tags=["curriculum"])


@router.get("", response_model=List[CurriculumPhaseResponse])
def get_curriculum(_user=Depends(get_current_user)):
    """전체 커리큘럼 Phase 목록 + 태스크 진행률 반환"""
    supabase = get_supabase()

    phases_res = (
        supabase.table("curriculum_phases")
        .select("*")
        .order("phase")
        .execute()
    )
    phases = phases_res.data or []

    tasks_res = supabase.table("phase_tasks").select("*").execute()
    tasks = tasks_res.data or []

    tasks_by_phase: dict = {}
    for task in tasks:
        pid = task["phase_id"]
        tasks_by_phase.setdefault(pid, []).append(task)

    result = []
    for phase in phases:
        phase_tasks = tasks_by_phase.get(phase["id"], [])
        if phase_tasks:
            avg_progress = sum(t["progress"] for t in phase_tasks) // len(phase_tasks)
        else:
            avg_progress = 0

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
                tasks=[
                    PhaseTaskResponse(
                        id=t["id"],
                        name=t["name"],
                        progress=t["progress"],
                    )
                    for t in phase_tasks
                ],
            )
        )
    return result


@router.get("/{phase_id}/tasks", response_model=List[PhaseTaskResponse])
def get_phase_tasks(phase_id: int, _user=Depends(get_current_user)):
    """특정 Phase의 태스크 목록 반환"""
    supabase = get_supabase()

    phase_res = (
        supabase.table("curriculum_phases")
        .select("id")
        .eq("id", phase_id)
        .single()
        .execute()
    )
    if not phase_res.data:
        raise HTTPException(status_code=404, detail="커리큘럼 Phase를 찾을 수 없습니다.")

    tasks_res = (
        supabase.table("phase_tasks")
        .select("*")
        .eq("phase_id", phase_id)
        .execute()
    )
    tasks = tasks_res.data or []
    return [PhaseTaskResponse(id=t["id"], name=t["name"], progress=t["progress"]) for t in tasks]

