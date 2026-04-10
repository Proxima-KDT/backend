import uuid
import json
from typing import Optional
from openai import AsyncOpenAI
from app.config import get_settings
from app.utils.prompts import (
    get_interview_system_prompt,
    get_report_prompt,
    COMPANY_CONTEXT,
    POSITION_CONTEXT,
)

# 인메모리 세션 저장소 (추후 Supabase Redis로 교체)
_sessions: dict = {}

TOTAL_QUESTIONS = 10

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        # pydantic_settings는 os.environ에 전파하지 않으므로 명시적으로 전달
        _client = AsyncOpenAI(api_key=get_settings().OPENAI_API_KEY)
    return _client


async def start_interview(
    company: str,
    position: str,
    interview_type: str,
    user_id: str,
) -> dict:
    session_id = str(uuid.uuid4())
    system_prompt = get_interview_system_prompt(company, position, interview_type)

    # 첫 질문 생성
    response = await _get_client().chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": "면접을 시작해주세요. 첫 번째 질문을 해주세요.",
            },
        ],
        temperature=0.7,
        max_tokens=200,
    )
    first_question = response.choices[0].message.content.strip()

    _sessions[session_id] = {
        "user_id": user_id,
        "company": company,
        "position": position,
        "interview_type": interview_type,
        "system_prompt": system_prompt,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "assistant", "content": first_question},
        ],
        "qa_pairs": [],
        "current_question": first_question,
        "question_count": 1,
    }

    return {
        "session_id": session_id,
        "first_question": first_question,
        "total_questions": TOTAL_QUESTIONS,
    }


async def process_answer(session_id: str, answer: str) -> dict:
    session = _sessions.get(session_id)
    if not session:
        raise ValueError("세션을 찾을 수 없습니다.")

    # 답변 저장
    session["messages"].append({"role": "user", "content": answer})
    session["qa_pairs"].append({
        "question": session["current_question"],
        "answer": answer,
    })

    question_count = session["question_count"]

    # 마지막 질문이었으면 종료
    if question_count >= TOTAL_QUESTIONS:
        return {
            "next_question": None,
            "question_number": question_count,
            "total_questions": TOTAL_QUESTIONS,
            "is_finished": True,
        }

    # 다음 질문 생성
    next_q_number = question_count + 1
    # system role로 지시 — user 대화 흐름 오염 방지
    session["messages"].append({
        "role": "system",
        "content": f"현재 {question_count}번째 질문까지 완료했습니다. 이제 {next_q_number}번째 면접 질문을 해주세요.",
    })

    response = await _get_client().chat.completions.create(
        model="gpt-4o-mini",
        messages=session["messages"],
        temperature=0.7,
        max_tokens=200,
    )
    next_question = response.choices[0].message.content.strip()

    # (시스템 메시지 제거 후) 실제 AI 응답 추가
    session["messages"].pop()  # 시스템 지시 제거
    session["messages"].append({"role": "assistant", "content": next_question})
    session["current_question"] = next_question
    session["question_count"] = next_q_number

    return {
        "next_question": next_question,
        "question_number": next_q_number,
        "total_questions": TOTAL_QUESTIONS,
        "is_finished": False,
    }


async def end_interview(session_id: str, user_id: str) -> dict:
    session = _sessions.get(session_id)
    if not session:
        raise ValueError("세션을 찾을 수 없습니다.")

    report_prompt = get_report_prompt(
        company=session["company"],
        position=session["position"],
        interview_type=session["interview_type"],
        qa_pairs=session["qa_pairs"],
    )

    response = await _get_client().chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": report_prompt}],
        temperature=0.3,
        max_tokens=600,
        response_format={"type": "json_object"},
    )

    try:
        report = json.loads(response.choices[0].message.content)
    except json.JSONDecodeError:
        report = {
            "total_score": 70,
            "categories": [
                {"name": "기술 지식", "score": 70},
                {"name": "문제 해결", "score": 70},
                {"name": "커뮤니케이션", "score": 70},
                {"name": "논리적 사고", "score": 70},
            ],
            "summary": "면접이 완료되었습니다. 상세 분석을 생성하는 중 오류가 발생했습니다.",
            "improvements": ["답변을 더 구체적으로 작성해보세요.", "예시를 들어 설명해보세요.", "경험과 연결지어 답변해보세요."],
        }

    total_score = report.get("total_score", 0)

    # mock_interviews 테이블에 저장 + skill_scores.ai_interview 업데이트
    try:
        from app.utils.supabase_client import get_supabase
        supabase = get_supabase()

        supabase.table("mock_interviews").insert({
            "user_id": user_id,
            "company": session["company"],
            "position": session["position"],
            "interview_type": session["interview_type"],
            "questions": [qa["question"] for qa in session["qa_pairs"]],
            "answers": [qa["answer"] for qa in session["qa_pairs"]],
            "report": report,
            "score": total_score,
        }).execute()

        # 최근 5회 면접 점수 평균으로 ai_interview 업데이트
        recent = (
            supabase.table("mock_interviews")
            .select("score")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(5)
            .execute()
        )
        scores = [r["score"] for r in (recent.data or []) if r.get("score") is not None]
        if scores:
            avg_score = round(sum(scores) / len(scores))
            supabase.table("skill_scores").upsert(
                {"user_id": user_id, "ai_interview": avg_score},
                on_conflict="user_id",
            ).execute()
    except Exception as e:
        import logging
        logging.getLogger(__name__).error("면접 결과 저장 실패: %s", e)

    # 세션 정리 (메모리 절약)
    _sessions.pop(session_id, None)

    return report


def get_interview_options() -> dict:
    """프론트엔드 드롭다운 옵션 반환"""
    companies = [
        {"value": "naver", "label": "네이버"},
        {"value": "kakao", "label": "카카오"},
        {"value": "line", "label": "라인"},
        {"value": "coupang", "label": "쿠팡"},
        {"value": "samsung_sds", "label": "삼성SDS"},
        {"value": "lg_cns", "label": "LG CNS"},
        {"value": "sk_telecom", "label": "SK텔레콤"},
        {"value": "toss", "label": "토스"},
        {"value": "kakaobank", "label": "카카오뱅크"},
        {"value": "startup", "label": "스타트업 (일반)"},
    ]
    positions = [
        {"value": "frontend", "label": "프론트엔드 개발자"},
        {"value": "backend", "label": "백엔드 개발자"},
        {"value": "fullstack", "label": "풀스택 개발자"},
        {"value": "data_engineer", "label": "데이터 엔지니어"},
        {"value": "devops", "label": "DevOps/클라우드 엔지니어"},
        {"value": "mobile", "label": "모바일 개발자"},
    ]
    interview_types = [
        {"value": "technical", "label": "기술 면접"},
        {"value": "personality", "label": "인성 면접"},
        {"value": "mixed", "label": "복합 면접 (기술+인성)"},
    ]
    return {"companies": companies, "positions": positions, "interview_types": interview_types}
