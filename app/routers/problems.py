from fastapi import APIRouter, HTTPException, Depends
from typing import Optional
from app.dependencies import get_current_user
from app.utils.supabase_client import get_supabase
from app.schemas.problem import ProblemResponse, ProblemSubmitRequest, ProblemEvaluationResponse
from app.services import ai_service

router = APIRouter(prefix="/api/problems", tags=["problems"])


@router.get("", response_model=list)
def get_problems(
    date: Optional[str] = None,
    user=Depends(get_current_user),
):
    """데일리 문제 목록 조회. date 파라미터(YYYY-MM-DD)로 필터링 가능."""
    supabase = get_supabase()

    query = supabase.table("problems").select("*")
    if date:
        query = query.eq("date", date)
    query = query.order("date", desc=True)

    problems_res = query.execute()
    problems = problems_res.data or []

    # 현재 사용자의 제출 기록 조회
    problem_ids = [p["id"] for p in problems]
    submissions_by_problem: dict = {}
    if problem_ids:
        subs_res = (
            supabase.table("submissions")
            .select("problem_id, score, is_correct")
            .eq("user_id", user["id"])
            .in_("problem_id", problem_ids)
            .execute()
        )
        for s in (subs_res.data or []):
            submissions_by_problem[s["problem_id"]] = s

    result = []
    for p in problems:
        sub = submissions_by_problem.get(p["id"])
        result.append(
            ProblemResponse(
                id=p["id"],
                title=p["title"],
                description=p.get("description"),
                type=p["type"],
                difficulty=p.get("difficulty"),
                tags=p.get("tags") or [],
                date=str(p["date"]) if p.get("date") else None,
                submitted=sub is not None,
                score=sub["score"] if sub else None,
                choices=p.get("choices"),
                correct_answer=None,  # 정답 노출 금지
            )
        )
    return result


@router.get("/{problem_id}", response_model=ProblemResponse)
def get_problem(problem_id: int, user=Depends(get_current_user)):
    """문제 상세 조회"""
    supabase = get_supabase()

    problem_res = (
        supabase.table("problems")
        .select("*")
        .eq("id", problem_id)
        .single()
        .execute()
    )
    if not problem_res.data:
        raise HTTPException(status_code=404, detail="문제를 찾을 수 없습니다.")
    p = problem_res.data

    # 사용자 제출 기록 확인
    sub_res = (
        supabase.table("submissions")
        .select("score, is_correct, answer")
        .eq("user_id", user["id"])
        .eq("problem_id", problem_id)
        .order("submitted_at", desc=True)
        .limit(1)
        .execute()
    )
    sub = sub_res.data[0] if sub_res.data else None

    return ProblemResponse(
        id=p["id"],
        title=p["title"],
        description=p.get("description"),
        type=p["type"],
        difficulty=p.get("difficulty"),
        tags=p.get("tags") or [],
        date=str(p["date"]) if p.get("date") else None,
        submitted=sub is not None,
        score=sub["score"] if sub else None,
        choices=p.get("choices"),
        correct_answer=sub["answer"] if (sub and p["type"] == "multiple_choice") else None,
    )


@router.post("/{problem_id}/submit", response_model=ProblemEvaluationResponse)
async def submit_problem(
    problem_id: int,
    body: ProblemSubmitRequest,
    user=Depends(get_current_user),
):
    """문제 답안 제출 및 채점"""
    supabase = get_supabase()

    problem_res = (
        supabase.table("problems")
        .select("*")
        .eq("id", problem_id)
        .single()
        .execute()
    )
    if not problem_res.data:
        raise HTTPException(status_code=404, detail="문제를 찾을 수 없습니다.")
    p = problem_res.data

    # 이미 제출한 경우 재제출 방지
    existing_res = (
        supabase.table("submissions")
        .select("id")
        .eq("user_id", user["id"])
        .eq("problem_id", problem_id)
        .execute()
    )
    if existing_res.data:
        raise HTTPException(status_code=409, detail="이미 제출한 문제입니다.")

    is_correct: bool = False
    score: int = 0
    feedback: Optional[str] = None

    if p["type"] == "multiple_choice":
        correct = str(p.get("correct_answer", ""))
        is_correct = body.answer.strip() == correct.strip()
        score = 100 if is_correct else 0
        feedback = "정답입니다!" if is_correct else "오답입니다. 다시 풀어보세요."

    elif p["type"] in ("short_answer", "code"):
        grading = await ai_service.grade_answer(
            problem_type=p["type"],
            title=p["title"],
            description=p.get("description", ""),
            user_answer=body.answer,
        )
        is_correct = grading["is_correct"]
        score = grading["score"]
        feedback = grading["feedback"]
    else:
        score = 0
        feedback = "채점을 완료했습니다."

    # 제출 기록 저장
    supabase.table("submissions").insert(
        {
            "problem_id": problem_id,
            "user_id": user["id"],
            "answer": body.answer,
            "is_correct": is_correct,
            "score": score,
            "feedback": feedback,
        }
    ).execute()

    return ProblemEvaluationResponse(
        is_correct=is_correct,
        score=score,
        feedback=feedback,
    )


@router.get("/{problem_id}/evaluation", response_model=ProblemEvaluationResponse)
async def get_problem_evaluation(problem_id: int, user=Depends(get_current_user)):
    """제출한 문제의 채점 결과 조회"""
    supabase = get_supabase()

    sub_res = (
        supabase.table("submissions")
        .select("is_correct, score, feedback")
        .eq("user_id", user["id"])
        .eq("problem_id", problem_id)
        .order("submitted_at", desc=True)
        .limit(1)
        .execute()
    )
    if not sub_res.data:
        raise HTTPException(status_code=404, detail="제출 기록이 없습니다.")

    sub = sub_res.data[0]
    return ProblemEvaluationResponse(
        is_correct=sub.get("is_correct", False),
        score=sub.get("score", 0),
        feedback=sub.get("feedback"),
    )

