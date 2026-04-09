from typing import List
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form
from app.dependencies import get_current_user
from app.utils.supabase_client import get_supabase
from app.schemas.assessment import AssessmentResponse, AssessmentSubmitResponse

router = APIRouter(prefix="/api/assessments", tags=["assessments"])


@router.get("", response_model=List[AssessmentResponse])
async def list_assessments(user=Depends(get_current_user)):
    """평가 목록 + 학생 제출 현황 조회"""
    supabase = get_supabase()

    assessments_res = (
        supabase.table("assessments")
        .select("*")
        .order("phase_id")
        .execute()
    )
    assessments = assessments_res.data or []

    # 학생 제출 현황 일괄 조회
    student_res = (
        supabase.table("assessment_submissions")
        .select("*")
        .eq("student_id", user["id"])
        .execute()
    )
    student_map = {str(sa["assessment_id"]): sa for sa in (student_res.data or [])}

    result = []
    for a in assessments:
        aid = str(a["id"])
        sa = student_map.get(aid)

        result.append(
            AssessmentResponse(
                id=aid,
                phase_id=a.get("phase_id"),
                phase_title=a.get("phase_title"),
                subject=a.get("subject"),
                description=a.get("description"),
                status=sa["status"] if sa else _compute_assessment_status(a),
                period={"start": a.get("period_start"), "end": a.get("period_end")},
                requirements=a.get("requirements") or [],
                coverage_topics=a.get("coverage_topics") or [],
                rubric=a.get("rubric") or [],
                max_score=a.get("max_score", 100),
                score=sa.get("score") if sa else None,
                passed=sa.get("passed") if sa else None,
                feedback=sa.get("feedback") if sa else None,
                submitted_files=sa.get("files") or [] if sa else [],
                submitted_at=sa.get("submitted_at") if sa else None,
            )
        )
    return result


@router.post("/{assessment_id}/submit", response_model=AssessmentSubmitResponse)
async def submit_assessment(
    assessment_id: str,
    files: List[UploadFile] = File(...),
    user=Depends(get_current_user),
):
    """평가 제출 (파일 업로드)"""
    supabase = get_supabase()
    from datetime import datetime

    # 평가 가져오기 및 유효성 확인
    assessment_res = (
        supabase.table("assessments")
        .select("id, period_end")
        .eq("id", assessment_id)
        .execute()
    )
    if not assessment_res.data:
        raise HTTPException(status_code=404, detail="평가를 찾을 수 없습니다.")

    # Supabase Storage에 파일 업로드
    uploaded_files = []
    for file in files:
        contents = await file.read()
        path = f"assessments/{assessment_id}/{user['id']}/{file.filename}"
        supabase.storage.from_("uploads").upload(path, contents, {"content-type": file.content_type or "application/octet-stream"})
        uploaded_files.append({"name": file.filename, "path": path})

    now_str = datetime.now().isoformat()

    # 학생 이름 조회
    user_res = supabase.table("users").select("name").eq("id", user["id"]).execute()
    student_name = user_res.data[0]["name"] if user_res.data else ""

    # upsert assessment_submissions
    existing_res = (
        supabase.table("assessment_submissions")
        .select("id, status")
        .eq("assessment_id", assessment_id)
        .eq("student_id", user["id"])
        .execute()
    )

    if existing_res.data:
        existing = existing_res.data[0] if isinstance(existing_res.data, list) else existing_res.data
        if existing["status"] not in ("resubmit_required", "open", "pending", "locked"):
            raise HTTPException(status_code=409, detail="이미 제출된 평가입니다.")
        supabase.table("assessment_submissions").update(
            {"status": "submitted", "files": uploaded_files, "submitted_at": now_str}
        ).eq("id", existing["id"]).execute()
        record_id = str(existing["id"])
    else:
        res = (
            supabase.table("assessment_submissions")
            .insert(
                {
                    "assessment_id": assessment_id,
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

    return AssessmentSubmitResponse(id=record_id, status="submitted", submitted_at=now_str)


def _compute_assessment_status(assessment: dict) -> str:
    """학생 제출 기록 없을 때의 기본 상태 계산 (기간 기반)"""
    from datetime import date

    today = date.today().isoformat()
    start = assessment.get("period_start", "")
    end = assessment.get("period_end", "")

    if end and today > end:
        return "locked"
    if start and today >= start:
        return "open"
    return "locked"

