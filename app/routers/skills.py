from fastapi import APIRouter, Depends
from app.dependencies import get_current_user
from app.utils.supabase_client import get_supabase
from app.schemas.skill import SkillScoreResponse, SkillScoreUpdateRequest

router = APIRouter(prefix="/api/skills", tags=["skills"])


@router.get("", response_model=SkillScoreResponse)
def get_skill_scores(user=Depends(get_current_user)):
    """스킬 5축 점수 조회"""
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


@router.put("")
def update_skill_scores(
    body: SkillScoreUpdateRequest, user=Depends(get_current_user)
):
    """스킬 점수 갱신 (upsert)"""
    supabase = get_supabase()

    update_data = {"user_id": user["id"]}
    if body.attendance is not None:
        update_data["attendance"] = body.attendance
    if body.ai_speaking is not None:
        update_data["ai_speaking"] = body.ai_speaking
    if body.ai_interview is not None:
        update_data["ai_interview"] = body.ai_interview
    if body.portfolio is not None:
        update_data["portfolio"] = body.portfolio
    if body.project_assignment_exam is not None:
        update_data["project_assignment_exam"] = body.project_assignment_exam

    supabase.table("skill_scores").upsert(
        update_data, on_conflict="user_id"
    ).execute()

    return {"message": "스킬 점수가 업데이트되었습니다."}

