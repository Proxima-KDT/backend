from fastapi import APIRouter, HTTPException, Depends
from app.dependencies import get_current_user
from app.utils.supabase_client import get_supabase
from app.schemas.submission import QuizSubmitRequest, QuizResultResponse

router = APIRouter(prefix="/api/submissions", tags=["submissions"])


@router.get("/concept/{concept_id}")
def get_concept_submissions(concept_id: str, user=Depends(get_current_user)):
    """사용자가 해당 개념에서 푼 문제들의 제출 기록 조회"""
    supabase = get_supabase()

    # 1. 개념에 속한 모든 문제 ID 조회
    problems_res = (
        supabase.table("problems")
        .select("id")
        .eq("concept_id", concept_id)
        .execute()
    )
    problem_ids = [p["id"] for p in (problems_res.data or [])]

    if not problem_ids:
        return {"submissions": []}

    # 2. 사용자가 푼 문제들의 제출 기록 조회 (최신순)
    submissions_res = (
        supabase.table("submissions")
        .select("problem_id, selected_answer, is_correct")
        .eq("user_id", user["id"])
        .in_("problem_id", problem_ids)
        .order("submitted_at", desc=True)
        .execute()
    )

    # 중복 기록이 있을 경우 problem_id당 최신 기록만 유지
    seen = set()
    latest_submissions = []
    for sub in (submissions_res.data or []):
        if sub["problem_id"] not in seen:
            seen.add(sub["problem_id"])
            latest_submissions.append(sub)

    return {
        "submissions": latest_submissions,
        "total_problems": len(problem_ids),
    }


@router.post("/quiz", response_model=QuizResultResponse)
def submit_quiz(body: QuizSubmitRequest, user=Depends(get_current_user)):
    """개념 퀴즈 일괄 제출 및 채점 — submissions 테이블에 각 문제별 기록 저장"""
    supabase = get_supabase()

    print(f"[DEBUG] Quiz submission received: concept_id={body.concept_id}, answers count={len(body.answers)}")
    print(f"[DEBUG] User ID: {user['id']}, First answer: {body.answers[0] if body.answers else 'None'}")

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

        # 개별 제출 기록 저장 (중복 방지: 기존 기록 삭제 후 새로 저장)
        try:
            # 기존 기록이 있으면 삭제
            supabase.table("submissions").delete().eq("user_id", user["id"]).eq("problem_id", pid).execute()

            # 새 기록 저장
            supabase.table("submissions").insert(
                {
                    "user_id": user["id"],
                    "problem_id": pid,
                    "selected_answer": selected,
                    "is_correct": is_correct,
                    "score": 100 if is_correct else 0,
                }
            ).execute()
        except Exception as e:
            print(f"Failed to save submission for problem {pid}: {str(e)}")

    total = len(details)
    score = int((correct_count / total) * 100) if total > 0 else 0

    return QuizResultResponse(
        concept_id=body.concept_id,
        total_problems=total,
        correct_count=correct_count,
        score=score,
        details=details,
    )

