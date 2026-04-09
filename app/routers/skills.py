from typing import List
from fastapi import APIRouter, Depends
from app.dependencies import get_current_user
from app.utils.supabase_client import get_supabase
from app.schemas.skill import SkillScoreResponse, SkillScoreUpdateRequest

router = APIRouter(prefix="/api/skills", tags=["skills"])


@router.get("", response_model=List[SkillScoreResponse])
def get_skill_scores(user=Depends(get_current_user)):
    """스킬 카테고리별 점수 조회"""
    supabase = get_supabase()

    res = (
        supabase.table("skill_scores")
        .select("category, score, skill_name")
        .eq("user_id", user["id"])
        .execute()
    )
    scores = res.data or []

    return [SkillScoreResponse(category=s["category"], score=s.get("score", 0)) for s in scores]


@router.put("/{category}")
def update_skill_score(
    category: str, body: SkillScoreUpdateRequest, user=Depends(get_current_user)
):
    """스킬 점수 갱신 (upsert)"""
    supabase = get_supabase()

    supabase.table("skill_scores").upsert(
        {
            "user_id": user["id"],
            "category": category,
            "score": body.score,
        },
        on_conflict="user_id,category",
    ).execute()

    return {"category": category, "score": body.score}

