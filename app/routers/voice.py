import random
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from app.dependencies import get_current_user
from app.utils.supabase_client import get_supabase
from app.schemas.voice import VoiceAnalyzeRequest, VoiceAnalyzeResponse, VoiceHistoryResponse, VoiceTopicResponse
from app.config import get_settings

router = APIRouter(prefix="/api/voice-feedback", tags=["voice"])


async def _analyze_voice_with_ai(topic: str, transcript: str, keywords: list) -> dict:
    """gpt-4.1-nano로 발화 내용 분석"""
    from openai import AsyncOpenAI
    import json

    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    system_prompt = (
        "당신은 IT 개발자 교육 과정의 발표 평가 AI입니다. "
        "학습자의 발화 내용을 분석하고 반드시 아래 JSON 형식으로만 응답하세요:\n"
        '{"score": 0~100 정수, "feedback": "피드백 문자열", '
        '"tip": "구체적인 개선 예시 문장 1~2줄", '
        '"keyword_results": [{"word": "키워드", "status": "correct|inaccurate|missing"}]}\n'
        "feedback 작성 기준: 잘한 점과 부족한 점을 2~3문장으로 간결하게.\n"
        "tip 작성 기준: '예를 들어 ~라고 말하면 더 좋습니다' 형식으로 "
        "누락되거나 부족한 키워드를 포함한 모범 답변 일부를 제시하세요. "
        "tip은 학습자가 바로 따라 말할 수 있는 구체적인 예시 문장이어야 합니다.\n"
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
    except Exception as e:
        # AI 실패 시 간단한 키워드 매칭으로 폴백
        import logging
        logging.getLogger(__name__).error("AI 분석 실패: %s", e)
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


@router.get("/random-topic", response_model=VoiceTopicResponse)
async def get_random_topic(
    category: Optional[str] = Query(default=None),
    difficulty: Optional[str] = Query(default=None),
    user=Depends(get_current_user),
):
    """카테고리/난이도 필터로 랜덤 주제 반환"""
    supabase = get_supabase()
    query = supabase.table("voice_topics").select("*")
    if category:
        query = query.eq("category", category)
    if difficulty:
        query = query.eq("difficulty", difficulty)
    res = query.execute()
    topics = res.data or []
    if not topics:
        raise HTTPException(status_code=404, detail="조건에 맞는 주제가 없습니다")
    topic = random.choice(topics)
    return VoiceTopicResponse(
        id=topic["id"],
        category=topic["category"],
        difficulty=topic["difficulty"],
        question=topic["question"],
        description=topic.get("description"),
        keywords=topic.get("keywords") or [],
    )


@router.post("/analyze", response_model=VoiceAnalyzeResponse)
async def analyze_voice(body: VoiceAnalyzeRequest, user=Depends(get_current_user)):
    """발화 내용 AI 분석 및 결과 저장"""
    supabase = get_supabase()

    # topic_id가 제공된 경우 DB에서 주제/키워드 가져오기
    resolved_topic = body.topic
    resolved_keywords = body.keywords
    if body.topic_id:
        topic_res = supabase.table("voice_topics").select("*").eq("id", body.topic_id).execute()
        if topic_res.data:
            t = topic_res.data[0]
            resolved_topic = t["question"]
            resolved_keywords = t.get("keywords") or []

    analysis = await _analyze_voice_with_ai(resolved_topic, body.transcript, resolved_keywords)

    keyword_results = analysis.get("keyword_results", [])
    correct = sum(1 for k in keyword_results if k.get("status") == "correct")
    inaccurate = sum(1 for k in keyword_results if k.get("status") == "inaccurate")
    missing = sum(1 for k in keyword_results if k.get("status") == "missing")

    # DB 저장
    supabase.table("voice_feedbacks").insert(
        {
            "user_id": user["id"],
            "topic": resolved_topic,
            "topic_id": body.topic_id,
            "transcript": body.transcript,
            "score": analysis.get("score", 0),
            "feedback": analysis.get("feedback", ""),
            "tip": analysis.get("tip"),
            "keywords": keyword_results,
            "total_keywords": len(keyword_results),
            "correct_count": correct,
            "inaccurate_count": inaccurate,
            "missing_count": missing,
        }
    ).execute()

    # skill_scores.ai_speaking 업데이트 (최근 10회 평균)
    try:
        recent = (
            supabase.table("voice_feedbacks")
            .select("score")
            .eq("user_id", user["id"])
            .order("created_at", desc=True)
            .limit(10)
            .execute()
        )
        scores = [r["score"] for r in (recent.data or []) if r.get("score") is not None]
        if scores:
            avg_score = round(sum(scores) / len(scores))
            # upsert: 없으면 생성, 있으면 ai_speaking만 갱신
            supabase.table("skill_scores").upsert(
                {"user_id": user["id"], "ai_speaking": avg_score},
                on_conflict="user_id",
            ).execute()
    except Exception as e:
        import logging
        logging.getLogger(__name__).error("skill_scores ai_speaking 업데이트 실패: %s", e)

    return VoiceAnalyzeResponse(
        score=analysis.get("score", 0),
        total_keywords=len(keyword_results),
        correct=correct,
        inaccurate=inaccurate,
        missing=missing,
        feedback=analysis.get("feedback", ""),
        tip=analysis.get("tip"),
        keywords=[{"word": k["word"], "status": k["status"]} for k in keyword_results],
    )


@router.get("/history", response_model=List[VoiceHistoryResponse])
async def get_voice_history(user=Depends(get_current_user)):
    """발화 피드백 히스토리 조회"""
    supabase = get_supabase()

    res = (
        supabase.table("voice_feedbacks")
        .select("*")
        .eq("user_id", user["id"])
        .order("created_at", desc=True)
        .limit(20)
        .execute()
    )
    sessions = res.data or []

    result = []
    for s in sessions:
        # 날짜/시간 파싱
        created_at = s.get("created_at", "")
        date_part = created_at[:10] if created_at else ""
        time_part = created_at[11:16] if len(created_at) > 10 else ""

        kw_results = s.get("keywords") or []
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
                tip=s.get("tip"),
                transcript=s.get("transcript"),
                keywords=[{"word": k["word"], "status": k["status"]} for k in kw_results],
            )
        )
    return result

