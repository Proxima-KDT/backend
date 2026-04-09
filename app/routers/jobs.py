from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from app.dependencies import get_current_user
from app.utils.supabase_client import get_supabase
from app.schemas.job import JobResponse

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _calculate_match_score(job_tech_stack: list, user_skills: list) -> int:
    """기술 스택 겹치는 비율로 매칭 점수(0-100) 계산"""
    if not job_tech_stack:
        return 0
    if not user_skills:
        return 0

    job_normalized = {t.lower() for t in job_tech_stack}
    user_normalized = {s.lower() for s in user_skills}
    matched = job_normalized & user_normalized
    score = int(len(matched) / len(job_normalized) * 100)
    return min(score, 100)


@router.get("", response_model=List[JobResponse])
def list_jobs(
    search: Optional[str] = Query(None, description="회사/포지션/기술스택 검색"),
    user=Depends(get_current_user),
):
    """채용 공고 목록 조회 (매칭 점수 포함, 내림차순 정렬)"""
    supabase = get_supabase()

    # 학생의 관심 직무 조회 (users.target_jobs 기반)
    user_res = (
        supabase.table("users")
        .select("target_jobs")
        .eq("id", user["id"])
        .execute()
    )
    user_skills = (user_res.data[0].get("target_jobs") or []) if user_res.data else []

    # 채용 공고 조회
    query = supabase.table("jobs").select("*")
    jobs_res = query.execute()
    jobs = jobs_res.data or []

    result = []
    for j in jobs:
        tech_stack = j.get("tech_stack") or []
        match_score = _calculate_match_score(tech_stack, user_skills)

        job_response = JobResponse(
            id=str(j["id"]),
            company=j["company"],
            position=j["position"],
            tech_stack=tech_stack,
            location=j.get("location"),
            deadline=j.get("deadline"),
            experience=j.get("experience"),
            match_score=match_score,
        )
        result.append(job_response)

    # 매칭 점수 내림차순 정렬
    result.sort(key=lambda x: x.match_score, reverse=True)

    # 검색 필터
    if search:
        q = search.lower()
        result = [
            j for j in result
            if q in j.company.lower()
            or q in j.position.lower()
            or any(q in t.lower() for t in j.tech_stack)
            or (j.location and q in j.location.lower())
        ]

    return result

