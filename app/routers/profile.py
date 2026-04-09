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

    return ProfileResponse(
        id=str(p["id"]),
        name=p.get("name", ""),
        email=p.get("email") or user.get("email"),
        avatar_url=p.get("avatar_url"),
        role=p.get("role", "student"),
        target_jobs=p.get("target_jobs") or [],
        overall_score=p.get("overall_score", 0),
        tier=p.get("tier", "Beginner"),
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
    """레이더 차트용 스킬 점수 조회 (5축)"""
    supabase = get_supabase()

    res = (
        supabase.table("skill_scores")
        .select("*")
        .eq("user_id", user["id"])
        .execute()
    )
    if not res.data:
        return SkillScoreResponse()

    s = res.data[0]
    return SkillScoreResponse(
        attendance=s.get("attendance", 0),
        ai_speaking=s.get("ai_speaking", 0),
        ai_interview=s.get("ai_interview", 0),
        portfolio=s.get("portfolio", 0),
        project_assignment_exam=s.get("project_assignment_exam", 0),
        overall_score=s.get("overall_score", 0),
        tier=s.get("tier", "Beginner"),
    )

