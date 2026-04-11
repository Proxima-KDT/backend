from datetime import date, timedelta
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from app.dependencies import get_current_user
from app.utils.supabase_client import get_supabase
from app.schemas.profile import ProfileResponse, ProfileUpdateTargetJobs, SkillScoreResponse

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

    if course_id:
        course_res = (
            supabase.table("courses")
            .select("name")
            .eq("id", course_id)
            .execute()
        )
        if course_res.data:
            course_name = course_res.data[0].get("name")

    return ProfileResponse(
        id=str(p["id"]),
        name=p.get("name", ""),
        email=p.get("email") or user.get("email"),
        avatar_url=p.get("avatar_url"),
        role=p.get("role", "student"),
        target_jobs=p.get("target_jobs") or [],
        overall_score=p.get("overall_score", 0),
        tier=p.get("tier", "Beginner"),
        course_name=course_name,
        cohort_number=cohort_number,
        course_start_date=course_start_date,
        course_end_date=course_end_date,
    )


@router.put("/target-jobs")
def update_target_jobs(body: ProfileUpdateTargetJobs, user=Depends(get_current_user)):
    """목표 직종 업데이트"""
    supabase = get_supabase()

    supabase.table("users").update({"target_jobs": body.jobs}).eq(
        "id", user["id"]
    ).execute()
    return {"message": "목표 직종이 업데이트되었습니다.", "jobs": body.jobs}


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

