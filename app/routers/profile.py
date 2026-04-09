from typing import List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from app.dependencies import get_current_user
from app.utils.supabase_client import get_supabase
from app.schemas.profile import ProfileResponse, ProfileUpdateTargetJobs, SkillScoreResponse

router = APIRouter(prefix="/api/profile", tags=["profile"])


@router.get("/me", response_model=ProfileResponse)
def get_my_profile(user=Depends(get_current_user)):
    """내 프로필 조회 (코호트·멘토 정보 포함)"""
    supabase = get_supabase()

    res = (
        supabase.table("profiles")
        .select("*")
        .eq("user_id", user["id"])
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="프로필을 찾을 수 없습니다.")

    p = res.data[0]

    # 코호트 이름 조회
    cohort_name = None
    if p.get("cohort_id"):
        c_res = (
            supabase.table("cohorts")
            .select("name")
            .eq("id", p["cohort_id"])
            .execute()
        )
        if c_res.data:
            cohort_name = c_res.data[0]["name"]

    # 멘토 이름 조회
    mentor_name = None
    if p.get("mentor_id"):
        m_res = (
            supabase.table("profiles")
            .select("name")
            .eq("user_id", p["mentor_id"])
            .execute()
        )
        if m_res.data:
            mentor_name = m_res.data[0]["name"]

    return ProfileResponse(
        id=str(p["user_id"]),
        user_id=str(p["user_id"]),
        name=p.get("name", ""),
        email=p.get("email") or user.get("email"),
        avatar_url=p.get("avatar_url"),
        role=p.get("role", "student"),
        target_jobs=p.get("target_jobs") or [],
        cohort_id=str(p["cohort_id"]) if p.get("cohort_id") else None,
        cohort_name=cohort_name,
        mentor_id=str(p["mentor_id"]) if p.get("mentor_id") else None,
        mentor_name=mentor_name,
    )


@router.put("/target-jobs")
def update_target_jobs(body: ProfileUpdateTargetJobs, user=Depends(get_current_user)):
    """목표 직종 업데이트"""
    supabase = get_supabase()

    supabase.table("profiles").update({"target_jobs": body.jobs}).eq(
        "user_id", user["id"]
    ).execute()
    return {"message": "목표 직종이 업데이트되었습니다.", "jobs": body.jobs}


@router.post("/avatar")
async def upload_avatar(file: UploadFile = File(...), user=Depends(get_current_user)):
    """프로필 아바타 이미지 업로드"""
    supabase = get_supabase()

    # 이미지 파일 유효성 검사
    if file.content_type not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
        raise HTTPException(status_code=400, detail="지원하지 않는 이미지 형식입니다.")

    contents = await file.read()
    ext = file.filename.rsplit(".", 1)[-1] if "." in file.filename else "jpg"
    path = f"avatars/{user['id']}.{ext}"

    supabase.storage.from_("uploads").upload(
        path, contents, {"content-type": file.content_type, "upsert": "true"}
    )
    # public URL 가져오기
    url_res = supabase.storage.from_("uploads").get_public_url(path)
    avatar_url = url_res if isinstance(url_res, str) else url_res.get("publicUrl", "")

    supabase.table("profiles").update({"avatar_url": avatar_url}).eq("user_id", user["id"]).execute()
    return {"avatar_url": avatar_url}


@router.get("/skill-scores", response_model=List[SkillScoreResponse])
def get_skill_scores(user=Depends(get_current_user)):
    """레이더 차트용 스킬 점수 조회"""
    supabase = get_supabase()

    res = (
        supabase.table("skill_scores")
        .select("category, score")
        .eq("user_id", user["id"])
        .execute()
    )
    scores = res.data or []

    return [
        SkillScoreResponse(
            subject=s["category"],
            score=s.get("score", 0),
            fullMark=100,
        )
        for s in scores
    ]

