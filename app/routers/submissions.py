from fastapi import APIRouter, HTTPException, Depends
from app.dependencies import get_current_user
from app.utils.supabase_client import get_supabase
from app.schemas.submission import QuizSubmitRequest, QuizResultResponse

router = APIRouter(prefix="/api/submissions", tags=["submissions"])
quiz_router = APIRouter(prefix="/api/quiz", tags=["quiz"])


@quiz_router.post("/submit", response_model=QuizResultResponse)
def submit_quiz(body: QuizSubmitRequest, user=Depends(get_current_user)):
    """개념 퀴즈 일괄 제출 및 채점"""
    supabase = get_supabase()

    # 개념 존재 확인 (comprehensive는 subject id로 처리)
    if body.concept_id != "comprehensive":
        concept_res = (
            supabase.table("concepts")
            .select("id")
            .eq("id", body.concept_id)
            .single()
            .execute()
        )
        if not concept_res.data:
            raise HTTPException(status_code=404, detail="개념을 찾을 수 없습니다.")

    # 제출된 문제들의 정답 조회
    problem_ids = [a["problem_id"] for a in body.answers]
    if not problem_ids:
        raise HTTPException(status_code=400, detail="제출할 답안이 없습니다.")

    correct_answers_res = (
        supabase.table("concept_quiz_problems")
        .select("id, answer, explanation")
        .in_("id", problem_ids)
        .execute()
    )
    correct_map: dict = {
        item["id"]: {"answer": item["answer"], "explanation": item.get("explanation")}
        for item in (correct_answers_res.data or [])
    }

    details = []
    correct_count = 0

    for submission in body.answers:
        pid = submission["problem_id"]
        selected = submission.get("selected_answer")
        correct_info = correct_map.get(pid)

        if correct_info is None:
            continue

        is_correct = (selected == correct_info["answer"])
        if is_correct:
            correct_count += 1

        details.append(
            {
                "problem_id": pid,
                "selected": selected,
                "correct": correct_info["answer"],
                "is_correct": is_correct,
                "explanation": correct_info["explanation"],
            }
        )

    total = len(details)
    score = int((correct_count / total) * 100) if total > 0 else 0

    # 퀴즈 세션 저장
    session_res = (
        supabase.table("quiz_sessions")
        .insert(
            {
                "user_id": user["id"],
                "concept_id": body.concept_id,
                "total_problems": total,
                "correct_count": correct_count,
                "score": score,
                "details": details,
            }
        )
        .execute()
    )
    session_id = session_res.data[0]["id"] if session_res.data else None

    return QuizResultResponse(
        id=session_id or "",
        concept_id=body.concept_id,
        total_problems=total,
        correct_count=correct_count,
        score=score,
        details=details,
    )


@quiz_router.get("/results/{session_id}", response_model=QuizResultResponse)
def get_quiz_results(session_id: str, user=Depends(get_current_user)):
    """퀴즈 세션 결과 조회"""
    supabase = get_supabase()

    session_res = (
        supabase.table("quiz_sessions")
        .select("*")
        .eq("id", session_id)
        .eq("user_id", user["id"])
        .single()
        .execute()
    )
    if not session_res.data:
        raise HTTPException(status_code=404, detail="퀴즈 세션을 찾을 수 없습니다.")

    s = session_res.data
    return QuizResultResponse(
        id=s["id"],
        concept_id=s["concept_id"],
        total_problems=s["total_problems"],
        correct_count=s["correct_count"],
        score=s["score"],
        details=s.get("details"),
    )

