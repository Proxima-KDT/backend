from typing import List
from fastapi import APIRouter, Depends, HTTPException
from app.dependencies import get_current_user
from app.utils.supabase_client import get_supabase
from app.schemas.voice import VoiceAnalyzeRequest, VoiceAnalyzeResponse, VoiceHistoryResponse

router = APIRouter(prefix="/api/voice-feedback", tags=["voice"])


async def _analyze_voice_with_ai(topic: str, transcript: str, keywords: list) -> dict:
    """GPT-4o-mini로 발화 내용 분석"""
    from openai import AsyncOpenAI
    import json

    client = AsyncOpenAI()

    system_prompt = (
        "당신은 IT 개발자 교육 과정의 발표 평가 AI입니다. "
        "학습자의 발화 내용을 분석하고 반드시 아래 JSON 형식으로만 응답하세요:\n"
        '{"score": 0~100 정수, "feedback": "피드백 문자열", '
        '"keyword_results": [{"word": "키워드", "status": "correct|inaccurate|missing"}]}\n'
        "status 기준: correct=정확히 사용, inaccurate=잘못되거나 어색하게 사용, missing=언급 안됨"
    )

    user_prompt = (
        f"주제: {topic}\n"
        f"학습자 발화:\n{transcript}\n\n"
        f"평가해야 할 핵심 키워드: {', '.join(keywords) if keywords else '없음'}"
    )

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=800,
        )
        return json.loads(response.choices[0].message.content)
    except Exception:
        # AI 실패 시 간단한 키워드 매칭으로 폴백
        transcript_lower = transcript.lower()
        results = []
        for kw in keywords:
            status = "correct" if kw.lower() in transcript_lower else "missing"
            results.append({"word": kw, "status": status})
        return {
            "score": 50,
            "feedback": "AI 분석을 완료하지 못했습니다. 키워드 포함 여부만 기본 판단하였습니다.",
            "keyword_results": results,
        }


@router.post("/analyze", response_model=VoiceAnalyzeResponse)
async def analyze_voice(body: VoiceAnalyzeRequest, user=Depends(get_current_user)):
    """발화 내용 AI 분석 및 결과 저장"""
    supabase = get_supabase()

    analysis = await _analyze_voice_with_ai(body.topic, body.transcript, body.keywords)

    keyword_results = analysis.get("keyword_results", [])
    correct = sum(1 for k in keyword_results if k.get("status") == "correct")
    inaccurate = sum(1 for k in keyword_results if k.get("status") == "inaccurate")
    missing = sum(1 for k in keyword_results if k.get("status") == "missing")

    # DB 저장
    from datetime import datetime

    now = datetime.now()
    supabase.table("voice_feedback_sessions").insert(
        {
            "user_id": user["id"],
            "topic": body.topic,
            "transcript": body.transcript,
            "score": analysis.get("score", 0),
            "feedback": analysis.get("feedback", ""),
            "keyword_results": keyword_results,
            "correct_count": correct,
            "inaccurate_count": inaccurate,
            "missing_count": missing,
            "recorded_at": now.isoformat(),
        }
    ).execute()

    return VoiceAnalyzeResponse(
        score=analysis.get("score", 0),
        total_keywords=len(keyword_results),
        correct=correct,
        inaccurate=inaccurate,
        missing=missing,
        feedback=analysis.get("feedback", ""),
        keywords=[{"word": k["word"], "status": k["status"]} for k in keyword_results],
    )


@router.get("/history", response_model=List[VoiceHistoryResponse])
async def get_voice_history(user=Depends(get_current_user)):
    """발화 피드백 히스토리 조회"""
    supabase = get_supabase()

    res = (
        supabase.table("voice_feedback_sessions")
        .select("*")
        .eq("user_id", user["id"])
        .order("recorded_at", desc=True)
        .limit(20)
        .execute()
    )
    sessions = res.data or []

    result = []
    for s in sessions:
        # 날짜/시간 파싱
        recorded_at = s.get("recorded_at", "")
        date_part = recorded_at[:10] if recorded_at else ""
        time_part = recorded_at[11:16] if len(recorded_at) > 10 else ""

        kw_results = s.get("keyword_results") or []
        result.append(
            VoiceHistoryResponse(
                id=str(s["id"]),
                date=date_part,
                time=time_part,
                topic=s["topic"],
                duration=s.get("duration"),
                score=s.get("score", 0),
                correct=s.get("correct_count", 0),
                inaccurate=s.get("inaccurate_count", 0),
                missing=s.get("missing_count", 0),
                feedback=s.get("feedback"),
                transcript=s.get("transcript"),
                keywords=[{"word": k["word"], "status": k["status"]} for k in kw_results],
            )
        )
    return result

