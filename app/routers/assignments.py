from typing import List
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from app.dependencies import get_current_user
from app.utils.supabase_client import get_supabase
from app.schemas.assignment import (
    AssignmentResponse,
    AssignmentSubmitResponse,
    AssignmentFeedbackResponse,
)

router = APIRouter(prefix="/api/assignments", tags=["assignments"])


@router.get("", response_model=List[AssignmentResponse])
async def list_assignments(user=Depends(get_current_user)):
    """과제 목록 + 제출 현황 조회"""
    supabase = get_supabase()

    assignments_res = (
        supabase.table("assignments")
        .select("*")
        .order("due_date")
        .execute()
    )
    assignments = assignments_res.data or []

    # 학생 제출 현황 일괄 조회
    student_res = (
        supabase.table("assignment_submissions")
        .select("*")
        .eq("student_id", user["id"])
        .execute()
    )
    student_map = {str(sa["assignment_id"]): sa for sa in (student_res.data or [])}

    result = []
    for a in assignments:
        aid = str(a["id"])
        sa = student_map.get(aid)

        result.append(
            AssignmentResponse(
                id=aid,
                subject=a.get("subject"),
                title=a["title"],
                description=a.get("description"),
                status=sa["status"] if sa else "pending",
                due_date=a.get("due_date"),
                max_score=a.get("max_score", 100),
                score=sa.get("score") if sa else None,
                rubric=a.get("rubric"),
                feedback=sa.get("feedback") if sa else None,
                attachments=a.get("attachments") or [],
                submitted_files=sa.get("files") or [] if sa else [],
                submitted_at=sa.get("submitted_at") if sa else None,
            )
        )
    return result


@router.post("/{assignment_id}/submit", response_model=AssignmentSubmitResponse)
async def submit_assignment(
    assignment_id: str,
    files: List[UploadFile] = File(...),
    user=Depends(get_current_user),
):
    """과제 파일 제출"""
    supabase = get_supabase()
    from datetime import datetime

    assignment_res = (
        supabase.table("assignments")
        .select("id")
        .eq("id", assignment_id)
        .execute()
    )
    if not assignment_res.data:
        raise HTTPException(status_code=404, detail="과제를 찾을 수 없습니다.")

    # 파일 업로드
    uploaded_files = []
    for file in files:
        contents = await file.read()
        path = f"assignments/{assignment_id}/{user['id']}/{file.filename}"
        supabase.storage.from_("uploads").upload(
            path, contents, {"content-type": file.content_type or "application/octet-stream"}
        )
        uploaded_files.append({"name": file.filename, "path": path})

    now_str = datetime.now().isoformat()

    # 학생 이름 조회
    user_res = supabase.table("users").select("name").eq("id", user["id"]).execute()
    student_name = user_res.data[0]["name"] if user_res.data else ""

    existing_res = (
        supabase.table("assignment_submissions")
        .select("id, status")
        .eq("assignment_id", assignment_id)
        .eq("student_id", user["id"])
        .execute()
    )

    if existing_res.data:
        existing = existing_res.data[0] if isinstance(existing_res.data, list) else existing_res.data
        if existing["status"] == "graded":
            raise HTTPException(status_code=409, detail="채점이 완료된 과제는 재제출할 수 없습니다.")
        supabase.table("assignment_submissions").update(
            {"status": "submitted", "files": uploaded_files, "submitted_at": now_str}
        ).eq("id", existing["id"]).execute()
        record_id = str(existing["id"])
    else:
        res = (
            supabase.table("assignment_submissions")
            .insert(
                {
                    "assignment_id": assignment_id,
                    "student_id": user["id"],
                    "student_name": student_name,
                    "status": "submitted",
                    "files": uploaded_files,
                    "submitted_at": now_str,
                }
            )
            .execute()
        )
        record_id = str(res.data[0]["id"])

    return AssignmentSubmitResponse(id=record_id, status="submitted", submitted_at=now_str)


@router.get("/{assignment_id}/feedback", response_model=AssignmentFeedbackResponse)
async def get_assignment_feedback(assignment_id: str, user=Depends(get_current_user)):
    """과제 피드백 및 채점 결과 조회"""
    supabase = get_supabase()

    res = (
        supabase.table("assignment_submissions")
        .select("score, feedback, rubric_scores")
        .eq("assignment_id", assignment_id)
        .eq("student_id", user["id"])
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="제출 기록을 찾을 수 없습니다.")

    data = res.data[0] if isinstance(res.data, list) else res.data
    return AssignmentFeedbackResponse(
        score=data.get("score"),
        feedback=data.get("feedback"),
        rubric=data.get("rubric_scores"),
    )

