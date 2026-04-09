from openai import AsyncOpenAI

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    """OpenAI 클라이언트를 지연 초기화. API 키 없이 임포트해도 안전."""
    global _client
    if _client is None:
        _client = AsyncOpenAI()  # OPENAI_API_KEY 환경변수 자동 사용
    return _client


async def grade_answer(
    problem_type: str,
    title: str,
    description: str,
    user_answer: str,
) -> dict:
    """주관식·코드 문제를 GPT-4o-mini로 채점.

    Returns:
        {"is_correct": bool, "score": int (0-100), "feedback": str}
    """
    client = _get_client()

    if problem_type == "code":
        evaluation_focus = (
            "코드의 정확성, 효율성, 가독성, 엣지 케이스 처리를 기준으로 평가하세요."
        )
    else:  # short_answer
        evaluation_focus = (
            "핵심 개념 포함 여부, 정확성, 설명의 명확성을 기준으로 평가하세요."
        )

    system_prompt = (
        "당신은 IT 교육 과정의 채점 담당 AI입니다. "
        "학생의 답변을 평가하고 반드시 아래 JSON 형식으로만 응답하세요:\n"
        '{"is_correct": true/false, "score": 0~100 사이 정수, "feedback": "피드백 문자열"}\n'
        "is_correct는 score 70 이상이면 true, 미만이면 false로 설정하세요."
    )

    user_prompt = (
        f"문제 유형: {problem_type}\n"
        f"문제 제목: {title}\n"
        f"문제 설명:\n{description}\n\n"
        f"학생 답변:\n{user_answer}\n\n"
        f"평가 기준: {evaluation_focus}"
    )

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=500,
        )
        import json

        result = json.loads(response.choices[0].message.content)
        return {
            "is_correct": bool(result.get("is_correct", False)),
            "score": int(result.get("score", 0)),
            "feedback": str(result.get("feedback", "채점 결과를 가져올 수 없습니다.")),
        }
    except Exception:
        # AI 채점 실패 시 기본값 반환 (서비스 중단 방지)
        return {
            "is_correct": False,
            "score": 0,
            "feedback": "AI 채점 중 오류가 발생했습니다. 강사에게 문의하세요.",
        }


async def grade_assessment(
    assessment_description: str,
    rubric: list,
    max_score: int = 100,
) -> dict:
    """평가 제출물을 루브릭 기반으로 AI 채점.

    Returns:
        {"score": int, "feedback": str}
    """
    client = _get_client()

    rubric_text = "\n".join(
        f"- {r.get('item', '')}: 최대 {r.get('maxScore', 0)}점"
        for r in rubric
        if isinstance(r, dict)
    )

    system_prompt = (
        "당신은 IT 교육 과정의 평가 채점 AI입니다. "
        "루브릭 기준에 따라 제출물을 평가하고 "
        "반드시 아래 JSON 형식으로만 응답하세요:\n"
        f'{{"score": 0~{max_score} 사이 정수, "feedback": "종합 피드백 문자열"}}'
    )

    user_prompt = (
        f"평가 설명:\n{assessment_description}\n\n"
        f"루브릭:\n{rubric_text}\n\n"
        f"최대 점수: {max_score}\n\n"
        "위 기준으로 채점해주세요."
    )

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=500,
        )
        import json

        result = json.loads(response.choices[0].message.content)
        return {
            "score": min(int(result.get("score", 0)), max_score),
            "feedback": str(result.get("feedback", "")),
        }
    except Exception:
        return {
            "score": 0,
            "feedback": "AI 채점 중 오류가 발생했습니다.",
        }


async def generate_problems(
    topic: str,
    difficulty: str = "중",
    count: int = 3,
    problem_type: str = "multiple_choice",
) -> list:
    """GPT-4o-mini로 문제 자동 생성.

    Returns:
        List of dicts: [{"title": str, "description": str, "type": str,
                         "choices": list|None, "correct_answer": str, "tags": list}]
    """
    client = _get_client()

    type_instruction = {
        "multiple_choice": "4지선다 문제를 생성하세요. choices 배열에 4개의 선택지를 넣고 correct_answer에 정답 번호(1~4)를 넣으세요.",
        "short_answer": "주관식 문제를 생성하세요. choices는 null, correct_answer에 모범답안을 넣으세요.",
        "code": "코딩 문제를 생성하세요. choices는 null, correct_answer에 정답 코드를 넣으세요.",
    }

    system_prompt = (
        "당신은 IT 교육 문제 출제 AI입니다. "
        f"반드시 {count}개의 문제를 JSON 배열 형식으로만 응답하세요.\n"
        "각 문제 형식:\n"
        '{"title": "문제 제목", "description": "문제 설명", '
        f'"type": "{problem_type}", '
        '"choices": [...] 또는 null, "correct_answer": "정답", "tags": ["태그1"]}\n\n'
        f"{type_instruction.get(problem_type, '')}"
    )

    user_prompt = f"주제: {topic}\n난이도: {difficulty}\n문제 수: {count}개"

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.7,
            max_tokens=2000,
        )
        import json

        result = json.loads(response.choices[0].message.content)
        # 응답이 {"problems": [...]} 형태일 수 있음
        if isinstance(result, dict):
            problems = result.get("problems", result.get("items", []))
            if not isinstance(problems, list):
                problems = [result]
        elif isinstance(result, list):
            problems = result
        else:
            problems = []

        # 각 문제에 type 보장
        for p in problems:
            if "type" not in p:
                p["type"] = problem_type

        return problems[:count]
    except Exception:
        return []


async def summarize_counseling(transcript: str) -> dict:
    """상담 녹음 텍스트를 AI로 요약.

    Returns:
        {"summary": str, "action_items": list, "speakers": list, "duration": str}
    """
    client = _get_client()

    system_prompt = (
        "당신은 교육 상담 분석 AI입니다. "
        "상담 녹음 텍스트를 분석하여 반드시 아래 JSON 형식으로만 응답하세요:\n"
        '{"summary": "상담 요약 (3~5문장)", '
        '"action_items": ["후속 조치 1", "후속 조치 2"], '
        '"speakers": ["강사", "학생"], '
        '"duration": "약 N분"}'
    )

    user_prompt = f"상담 녹음 텍스트:\n\n{transcript}"

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=1000,
        )
        import json

        result = json.loads(response.choices[0].message.content)
        return {
            "summary": result.get("summary", ""),
            "action_items": result.get("action_items", []),
            "speakers": result.get("speakers", []),
            "duration": result.get("duration", ""),
        }
    except Exception:
        return {
            "summary": "AI 요약 중 오류가 발생했습니다.",
            "action_items": [],
            "speakers": [],
            "duration": "",
        }
