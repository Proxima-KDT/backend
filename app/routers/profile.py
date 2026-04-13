import time
from datetime import date, timedelta
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from app.dependencies import get_current_user
from app.utils.supabase_client import get_supabase
from app.schemas.profile import ProfileResponse, SkillScoreResponse, StudentFileListResponse, StudentFileItem

router = APIRouter(prefix="/api/profile", tags=["profile"])


@router.get("/me", response_model=ProfileResponse)
def get_my_profile(user=Depends(get_current_user)):
    """내 프로필 조회"""
    supabase = get_supabase()

    res = (
        supabase.table("users")
        .select("*")
        .eq("id", user["id"])
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="프로필을 찾을 수 없습니다.")

    p = res.data[0]

    # 교과 과정 정보 조회 (cohort_id → cohorts, course_id → courses)
    course_name = None
    cohort_number = None
    course_start_date = None
    course_end_date = None

    cohort_id = p.get("cohort_id")
    course_id = p.get("course_id")

    if cohort_id:
        cohort_res = (
            supabase.table("cohorts")
            .select("cohort_number, start_date, end_date")
            .eq("id", cohort_id)
            .execute()
        )
        if cohort_res.data:
            c = cohort_res.data[0]
            cohort_number = c.get("cohort_number")
            course_start_date = str(c["start_date"]) if c.get("start_date") else None
            course_end_date = str(c["end_date"]) if c.get("end_date") else None

    daily_start_time = None
    daily_end_time = None
    course_track_type = None
    teacher_name = None

    if course_id:
        course_res = (
            supabase.table("courses")
            .select("name, track_type, daily_start_time, daily_end_time")
            .eq("id", course_id)
            .execute()
        )
        if course_res.data:
            course_data = course_res.data[0]
            course_name = course_data.get("name")
            course_track_type = course_data.get("track_type")
            daily_start_time = str(course_data["daily_start_time"])[:5] if course_data.get("daily_start_time") else None
            daily_end_time = str(course_data["daily_end_time"])[:5] if course_data.get("daily_end_time") else None

        # 담당 강사 조회 (teacher_courses → users)
        tc_res = (
            supabase.table("teacher_courses")
            .select("teacher_id")
            .eq("course_id", course_id)
            .execute()
        )
        if tc_res.data:
            teacher_id = tc_res.data[0]["teacher_id"]
            teacher_res = (
                supabase.table("users")
                .select("name")
                .eq("id", teacher_id)
                .execute()
            )
            if teacher_res.data:
                teacher_name = teacher_res.data[0].get("name")

    # 담당 멘토 조회: mentor_courses 테이블 → users (teacher_courses와 동일 패턴)
    mentor_name = None
    if course_id:
        mc_res = (
            supabase.table("mentor_courses")
            .select("mentor_id")
            .eq("course_id", course_id)
            .limit(1)
            .execute()
        )
        if mc_res.data:
            mentor_id = mc_res.data[0]["mentor_id"]
            mentor_res = (
                supabase.table("users")
                .select("name")
                .eq("id", mentor_id)
                .execute()
            )
            if mentor_res.data:
                mentor_name = mentor_res.data[0].get("name")

    return ProfileResponse(
        id=str(p["id"]),
        name=p.get("name", ""),
        email=p.get("email") or user.get("email"),
        avatar_url=p.get("avatar_url"),
        role=p.get("role", "student"),
        overall_score=p.get("overall_score", 0),
        tier=p.get("tier", "Beginner"),
        course_name=course_name,
        course_track_type=course_track_type,
        cohort_number=cohort_number,
        course_start_date=course_start_date,
        course_end_date=course_end_date,
        daily_start_time=daily_start_time,
        daily_end_time=daily_end_time,
        teacher_name=teacher_name,
        mentor_name=mentor_name,
    )



@router.post("/avatar")
async def upload_avatar(file: UploadFile = File(...), user=Depends(get_current_user)):
    """프로필 아바타 이미지 업로드"""
    supabase = get_supabase()

    if file.content_type not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
        raise HTTPException(status_code=400, detail="지원하지 않는 이미지 형식입니다.")

    contents = await file.read()
    ext = file.filename.rsplit(".", 1)[-1] if "." in file.filename else "jpg"
    path = f"avatars/{user['id']}.{ext}"

    supabase.storage.from_("uploads").upload(
        path, contents, {"content-type": file.content_type, "upsert": "true"}
    )
    url_res = supabase.storage.from_("uploads").get_public_url(path)
    avatar_url = url_res if isinstance(url_res, str) else url_res.get("publicUrl", "")

    supabase.table("users").update({"avatar_url": avatar_url}).eq("id", user["id"]).execute()
    return {"avatar_url": avatar_url}


@router.get("/skill-scores", response_model=SkillScoreResponse)
def get_skill_scores(user=Depends(get_current_user)):
    """레이더 차트용 스킬 점수 조회 (5축) — 출석률은 실제 기록으로 동적 계산"""
    supabase = get_supabase()

    # skill_scores 조회
    res = (
        supabase.table("skill_scores")
        .select("*")
        .eq("user_id", user["id"])
        .execute()
    )
    s = res.data[0] if res.data else {}

    # 출석률을 실제 attendance 기록에서 동적 계산
    today = date.today()
    cur_res = (
        supabase.table("curriculum")
        .select("start_date")
        .eq("phase", 1)
        .execute()
    )
    if cur_res.data:
        training_start = date.fromisoformat(str(cur_res.data[0]["start_date"]))
    else:
        training_start = today

    # 훈련 시작일~오늘 평일 수 계산
    total_weekdays = sum(
        1 for i in range((today - training_start).days + 1)
        if (training_start + timedelta(days=i)).weekday() < 5
    )

    att_res = (
        supabase.table("attendance")
        .select("status")
        .eq("user_id", user["id"])
        .gte("date", training_start.isoformat())
        .lte("date", today.isoformat())
        .execute()
    )
    att_records = att_res.data or []
    attended = sum(1 for r in att_records if r.get("status") in ("present", "late"))
    attendance_score = round((attended / total_weekdays) * 100) if total_weekdays > 0 else 0

    # ai_speaking: voice_feedbacks 최근 10회 평균
    speaking_res = (
        supabase.table("voice_feedbacks")
        .select("score")
        .eq("user_id", user["id"])
        .order("created_at", desc=True)
        .limit(10)
        .execute()
    )
    speaking_scores = [r["score"] for r in (speaking_res.data or []) if r.get("score") is not None]
    ai_speaking = round(sum(speaking_scores) / len(speaking_scores)) if speaking_scores else 0

    # ai_interview: mock_interviews 최근 5회 평균
    interview_res = (
        supabase.table("mock_interviews")
        .select("score")
        .eq("user_id", user["id"])
        .order("created_at", desc=True)
        .limit(5)
        .execute()
    )
    interview_scores = [r["score"] for r in (interview_res.data or []) if r.get("score") is not None]
    ai_interview = round(sum(interview_scores) / len(interview_scores)) if interview_scores else 0

    portfolio = s.get("portfolio", 0)
    project_assignment_exam = s.get("project_assignment_exam", 0)

    # overall_score: 5축 평균으로 동적 계산
    overall_score = round(
        (attendance_score + ai_speaking + ai_interview + portfolio + project_assignment_exam) / 5
    )

    # tier 기준: Beginner < 40, Intermediate 40~69, Advanced 70~89, Master 90+
    if overall_score >= 90:
        tier = "Master"
    elif overall_score >= 70:
        tier = "Advanced"
    elif overall_score >= 40:
        tier = "Intermediate"
    else:
        tier = "Beginner"

    return SkillScoreResponse(
        attendance=attendance_score,
        ai_speaking=ai_speaking,
        ai_interview=ai_interview,
        portfolio=portfolio,
        project_assignment_exam=project_assignment_exam,
        overall_score=overall_score,
        tier=tier,
    )


# ── 이력서 / 포트폴리오 파일 ──────────────────────────────────

ALLOWED_MIME = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


@router.get("/files", response_model=StudentFileListResponse)
def get_my_files(user=Depends(get_current_user)):
    """내 이력서/포트폴리오 파일 목록"""
    supabase = get_supabase()
    res = (
        supabase.table("student_files")
        .select("*")
        .eq("student_id", user["id"])
        .order("uploaded_at", desc=True)
        .execute()
    )
    files = [
        StudentFileItem(
            id=f["id"],
            name=f.get("name", ""),
            type=f.get("type", ""),
            url=f.get("url", ""),
            uploaded_at=f.get("uploaded_at", "")[:10] if f.get("uploaded_at") else None,
        )
        for f in (res.data or [])
    ]
    return StudentFileListResponse(files=files)


@router.post("/files", response_model=StudentFileItem)
async def upload_student_file(
    file: UploadFile = File(...),
    file_type: str = Form(...),   # 'resume' | 'portfolio'
    user=Depends(get_current_user),
):
    """이력서 또는 포트폴리오 업로드"""
    if file_type not in ("resume", "portfolio"):
        raise HTTPException(status_code=400, detail="file_type은 'resume' 또는 'portfolio'여야 합니다.")
    if file.content_type not in ALLOWED_MIME:
        raise HTTPException(status_code=400, detail="PDF, DOC, DOCX, PPT, PPTX 파일만 업로드 가능합니다.")

    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="파일 크기는 10MB를 초과할 수 없습니다.")

    supabase = get_supabase()
    ts = int(time.time())
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else "bin"
    # Storage 경로는 ASCII만 허용 → 타임스탬프 + 확장자만 사용
    path = f"student-files/{user['id']}/{file_type}/{ts}.{ext}"

    supabase.storage.from_("uploads").upload(
        path, contents, {"content-type": file.content_type, "upsert": "true"}
    )
    url_res = supabase.storage.from_("uploads").get_public_url(path)
    url = url_res if isinstance(url_res, str) else url_res.get("publicUrl", "")

    insert_res = (
        supabase.table("student_files")
        .insert({
            "student_id": user["id"],
            "name": file.filename,
            "type": file_type,
            "url": url,
        })
        .execute()
    )
    f = insert_res.data[0]
    return StudentFileItem(
        id=f["id"],
        name=f.get("name", ""),
        type=f.get("type", ""),
        url=f.get("url", ""),
        uploaded_at=f.get("uploaded_at", "")[:10] if f.get("uploaded_at") else None,
    )


@router.delete("/files/{file_id}")
def delete_student_file(file_id: int, user=Depends(get_current_user)):
    """파일 삭제 (본인 파일만)"""
    supabase = get_supabase()

    res = (
        supabase.table("student_files")
        .select("*")
        .eq("id", file_id)
        .eq("student_id", user["id"])
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")

    file_data = res.data[0]
    # Storage에서도 삭제 (URL → path 추출)
    url = file_data.get("url", "")
    try:
        # URL 패턴: .../object/public/uploads/student-files/...
        if "student-files/" in url:
            storage_path = "student-files/" + url.split("student-files/")[-1]
            supabase.storage.from_("uploads").remove([storage_path])
    except Exception:
        pass  # Storage 삭제 실패해도 DB는 삭제

    supabase.table("student_files").delete().eq("id", file_id).execute()
    return {"message": "파일이 삭제되었습니다."}

