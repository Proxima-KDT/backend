"""
스킬 5축 동적 계산 서비스
- profile/skill-scores 엔드포인트와 동일 로직을 공유
- 강사 페이지(개별/목록)와 학생 마이페이지 양쪽에서 사용
"""

from datetime import date, timedelta
from typing import Dict, List


def _get_training_start(supabase) -> date:
    """Phase 1 시작일 조회"""
    today = date.today()
    cur_res = supabase.table("curriculum").select("start_date").eq("phase", 1).execute()
    if cur_res.data:
        try:
            return date.fromisoformat(str(cur_res.data[0]["start_date"]))
        except (ValueError, TypeError):
            pass
    return today


def _count_weekdays(start: date, end: date) -> int:
    """두 날짜 사이의 평일(월~금) 수 계산"""
    return sum(
        1 for i in range((end - start).days + 1)
        if (start + timedelta(days=i)).weekday() < 5
    )


def calculate_student_skills(supabase, user_id: str) -> Dict[str, int]:
    """
    학생 스킬 5축 동적 계산 (개별) — profile/skill-scores와 동일 로직
    - 출결: 훈련 시작일~오늘 평일 대비 출석 비율
    - AI 말하기: voice_feedbacks 최근 10회 평균
    - AI 면접: mock_interviews 최근 5회 평균
    - 포트폴리오: skill_scores 테이블 값
    - 프로젝트/과제/시험: skill_scores 테이블 값
    """
    today = date.today()
    training_start = _get_training_start(supabase)
    total_weekdays = _count_weekdays(training_start, today)

    # 출결
    att_res = (
        supabase.table("attendance")
        .select("status")
        .eq("user_id", user_id)
        .gte("date", training_start.isoformat())
        .lte("date", today.isoformat())
        .execute()
    )
    attended = sum(1 for r in (att_res.data or []) if r.get("status") in ("present", "late"))
    attendance_score = round((attended / total_weekdays) * 100) if total_weekdays > 0 else 0

    # AI 말하기 (voice_feedbacks 최근 10회 평균)
    speaking_res = (
        supabase.table("voice_feedbacks")
        .select("score")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(10)
        .execute()
    )
    speaking_scores = [r["score"] for r in (speaking_res.data or []) if r.get("score") is not None]
    ai_speaking = round(sum(speaking_scores) / len(speaking_scores)) if speaking_scores else 0

    # AI 면접 (mock_interviews 최근 5회 평균)
    interview_res = (
        supabase.table("mock_interviews")
        .select("score")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(5)
        .execute()
    )
    interview_scores = [r["score"] for r in (interview_res.data or []) if r.get("score") is not None]
    ai_interview = round(sum(interview_scores) / len(interview_scores)) if interview_scores else 0

    # 포트폴리오 & 프로젝트/과제/시험 (강사가 채점한 값 → skill_scores 테이블)
    sk_res = (
        supabase.table("skill_scores")
        .select("portfolio, project_assignment_exam")
        .eq("user_id", user_id)
        .execute()
    )
    sk = sk_res.data[0] if sk_res.data else {}

    return {
        "출결": attendance_score,
        "AI_말하기": ai_speaking,
        "AI_면접": ai_interview,
        "포트폴리오": sk.get("portfolio", 0),
        "프로젝트_과제_시험": sk.get("project_assignment_exam", 0),
    }


def calculate_students_skills_batch(supabase, student_ids: List[str]) -> Dict[str, Dict[str, int]]:
    """
    학생 목록 스킬 5축 배치 동적 계산 (N+1 방지 — 4개 쿼리로 전체 계산)
    Returns: {user_id: {"출결": int, "AI_말하기": int, ...}}
    """
    if not student_ids:
        return {}

    today = date.today()
    training_start = _get_training_start(supabase)
    total_weekdays = _count_weekdays(training_start, today)

    # 출결 (훈련 기간 내)
    att_res = (
        supabase.table("attendance")
        .select("user_id, status")
        .in_("user_id", student_ids)
        .gte("date", training_start.isoformat())
        .lte("date", today.isoformat())
        .execute()
    )
    att_by_user: Dict[str, List[str]] = {}
    for a in (att_res.data or []):
        att_by_user.setdefault(a["user_id"], []).append(a["status"])

    # AI 말하기 (voice_feedbacks 전체 조회 → Python에서 최근 10개 평균)
    speaking_res = (
        supabase.table("voice_feedbacks")
        .select("user_id, score, created_at")
        .in_("user_id", student_ids)
        .order("created_at", desc=True)
        .execute()
    )
    speaking_by_user: Dict[str, List[int]] = {}
    for r in (speaking_res.data or []):
        if r.get("score") is not None:
            speaking_by_user.setdefault(r["user_id"], []).append(r["score"])

    # AI 면접 (mock_interviews 전체 조회 → Python에서 최근 5개 평균)
    interview_res = (
        supabase.table("mock_interviews")
        .select("user_id, score, created_at")
        .in_("user_id", student_ids)
        .order("created_at", desc=True)
        .execute()
    )
    interview_by_user: Dict[str, List[int]] = {}
    for r in (interview_res.data or []):
        if r.get("score") is not None:
            interview_by_user.setdefault(r["user_id"], []).append(r["score"])

    # 포트폴리오 & 프로젝트 (강사 채점값 — skill_scores)
    sk_res = (
        supabase.table("skill_scores")
        .select("user_id, portfolio, project_assignment_exam")
        .in_("user_id", student_ids)
        .execute()
    )
    sk_by_user: Dict[str, dict] = {r["user_id"]: r for r in (sk_res.data or [])}

    result: Dict[str, Dict[str, int]] = {}
    for uid in student_ids:
        att_records = att_by_user.get(uid, [])
        attended = sum(1 for r in att_records if r in ("present", "late"))
        attendance_score = round((attended / total_weekdays) * 100) if total_weekdays > 0 else 0

        speaking_scores = speaking_by_user.get(uid, [])[:10]
        ai_speaking = round(sum(speaking_scores) / len(speaking_scores)) if speaking_scores else 0

        interview_scores = interview_by_user.get(uid, [])[:5]
        ai_interview = round(sum(interview_scores) / len(interview_scores)) if interview_scores else 0

        sk = sk_by_user.get(uid, {})
        result[uid] = {
            "출결": attendance_score,
            "AI_말하기": ai_speaking,
            "AI_면접": ai_interview,
            "포트폴리오": sk.get("portfolio", 0),
            "프로젝트_과제_시험": sk.get("project_assignment_exam", 0),
        }

    return result
