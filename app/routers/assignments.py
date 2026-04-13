from typing import List
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from app.dependencies import get_current_user
from app.utils.supabase_client import get_supabase
from app.schemas.assignment import (
    AssignmentResponse,
    AssignmentSubmitResponse,
    AssignmentFeedbackResponse,
    FileDeleteRequest,
    FileDeleteResponse,
)

router = APIRouter(prefix="/api/assignments", tags=["assignments"])


@router.get("", response_model=List[AssignmentResponse])
async def list_assignments(user=Depends(get_current_user)):
    """과제 목록 + 제출 현황 조회 — 본인이 수강하는 과정의 과제만 반환."""
    supabase = get_supabase()

    # 본인 course_id 조회 (없으면 빈 배열)
    me = (
        supabase.table("users")
        .select("course_id")
        .eq("id", user["id"])
        .limit(1)
        .execute()
    )
    my_course_id = (me.data[0].get("course_id") if me.data else None)
    if not my_course_id:
        return []

    assignments_res = (
        supabase.table("assignments")
        .select("*")
        .eq("course_id", my_course_id)
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

        # rubric 템플릿(assignments.rubric)과 채점 결과(submissions.rubric_scores)를 병합
        rubric_template = a.get("rubric") or []
        rubric_scores = (sa.get("rubric_scores") or []) if sa else []
        score_map = {rs["item"]: rs.get("score") for rs in rubric_scores}
        if rubric_template and score_map:
            merged_rubric = [
                {**r, "score": score_map.get(r.get("item"))}
                for r in rubric_template
            ]
        else:
            merged_rubric = rubric_template or None

        result.append(
            AssignmentResponse(
                id=aid,
                phase=a.get("phase"),
                subject=a.get("subject"),
                title=a["title"],
                description=a.get("description"),
                status=sa["status"] if sa else "pending",
                due_date=a.get("due_date"),
                max_score=a.get("max_score", 100),
                score=sa.get("score") if sa else None,
                rubric=merged_rubric,
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
    from datetime import datetime, timezone

    # URL path는 str이지만 DB의 assignment_id는 INTEGER
    try:
        assignment_id_int = int(assignment_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="잘못된 과제 ID입니다.")

    assignment_res = (
        supabase.table("assignments")
        .select("id")
        .eq("id", assignment_id_int)
        .execute()
    )
    if not assignment_res.data:
        raise HTTPException(status_code=404, detail="과제를 찾을 수 없습니다.")

    # 파일 업로드
    # 파일명에 한글 등 비ASCII 문자가 있으면 InvalidKey 오류가 발생하므로
    # path에는 UUID 기반 안전한 이름을 사용하고, 원본 파일명은 메타데이터로 보존
    import uuid
    import os
    uploaded_files = []
    for file in files:
        contents = await file.read()
        ext = os.path.splitext(file.filename)[1]  # 확장자 추출 (.py, .zip 등)
        safe_name = f"{uuid.uuid4().hex}{ext}"
        path = f"assignments/{assignment_id_int}/{user['id']}/{safe_name}"
        supabase.storage.from_("uploads").upload(
            path, contents, {"content-type": file.content_type or "application/octet-stream"}
        )
        uploaded_files.append({"name": file.filename, "path": path})

    now_str = datetime.now(timezone.utc).isoformat()

    # 학생 이름 조회
    user_res = supabase.table("users").select("name").eq("id", user["id"]).execute()
    student_name = user_res.data[0]["name"] if user_res.data else ""

    existing_res = (
        supabase.table("assignment_submissions")
        .select("id, status")
        .eq("assignment_id", assignment_id_int)
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
                    "assignment_id": assignment_id_int,
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


@router.delete("/{assignment_id}/files", response_model=FileDeleteResponse)
async def delete_submitted_file(
    assignment_id: str,
    body: FileDeleteRequest,
    user=Depends(get_current_user),
):
    """제출 파일 단건 삭제 (Storage + DB)"""
    supabase = get_supabase()

    try:
        assignment_id_int = int(assignment_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="잘못된 과제 ID입니다.")

    # 제출 기록 조회
    sub_res = (
        supabase.table("assignment_submissions")
        .select("id, status, files")
        .eq("assignment_id", assignment_id_int)
        .eq("student_id", user["id"])
        .execute()
    )
    if not sub_res.data:
        raise HTTPException(status_code=404, detail="제출 기록을 찾을 수 없습니다.")

    sub = sub_res.data[0]
    if sub["status"] == "graded":
        raise HTTPException(status_code=409, detail="채점 완료된 과제의 파일은 삭제할 수 없습니다.")

    files: list = sub.get("files") or []
    new_files = [f for f in files if f.get("path") != body.file_path]
    if len(new_files) == len(files):
        raise HTTPException(status_code=404, detail="해당 파일을 찾을 수 없습니다.")

    # Supabase Storage에서 실제 파일 삭제
    try:
        supabase.storage.from_("uploads").remove([body.file_path])
    except Exception:
        # Storage 삭제 실패해도 DB 업데이트는 진행 (고아 파일은 허용)
        pass

    # 모든 파일 삭제 시 submitted → pending 으로 복원 (resubmit_required는 유지)
    new_status = sub["status"]
    if not new_files and sub["status"] == "submitted":
        new_status = "pending"

    update_payload = {"files": new_files, "status": new_status}
    if new_status == "pending":
        update_payload["submitted_at"] = None

    supabase.table("assignment_submissions").update(update_payload).eq("id", sub["id"]).execute()

    return FileDeleteResponse(status=new_status, submitted_files=new_files)


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

