from fastapi import APIRouter, HTTPException, Depends
from app.dependencies import get_current_user
from app.utils.supabase_client import get_supabase
from app.schemas.submission import QuizSubmitRequest, QuizResultResponse

router = APIRouter(prefix="/api/submissions", tags=["submissions"])


@router.post("/quiz", response_model=QuizResultResponse)
def submit_quiz(body: QuizSubmitRequest, user=Depends(get_current_user)):
    """개념 퀴즈 일괄 제출 및 채점 — submissions 테이블에 각 문제별 기록 저장"""
    supabase = get_supabase()

    problem_ids = [a["problem_id"] for a in body.answers]
    if not problem_ids:
        raise HTTPException(status_code=400, detail="제출할 답안이 없습니다.")

    # 정답 조회
    correct_answers_res = (
        supabase.table("problems")
        .select("id, answer, explanation")
        .in_("id", problem_ids)
        .execute()
    )
    correct_map: dict = {
        item["id"]: {"answer": item.get("answer"), "explanation": item.get("explanation")}
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

        # 개별 제출 기록 저장
        supabase.table("submissions").insert(
            {
                "user_id": user["id"],
                "problem_id": pid,
                "selected_answer": selected,
                "is_correct": is_correct,
                "score": 100 if is_correct else 0,
            }
        ).execute()

    total = len(details)
    score = int((correct_count / total) * 100) if total > 0 else 0

    return QuizResultResponse(
        concept_id=body.concept_id,
        total_problems=total,
        correct_count=correct_count,
        score=score,
        details=details,
    )

