from openai import AsyncOpenAI

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    """OpenAI 클라이언트를 지연 초기화. config.py의 OPENAI_API_KEY 사용."""
    global _client
    if _client is None:
        from app.config import get_settings
        _client = AsyncOpenAI(api_key=get_settings().OPENAI_API_KEY)
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
    file_items: list = None,
) -> dict:
    """평가 제출물을 루브릭 기반으로 AI 채점.

    Returns:
        {"score": int, "rubric_scores": [...], "feedback": str}
    """
    client = _get_client()

    rubric_dicts = [
        {"item": r.get("item", ""), "maxScore": r.get("maxScore", 0)}
        for r in rubric
        if isinstance(r, dict)
    ]
    rubric_text = "\n".join(
        f"- {r['item']}: 최대 {r['maxScore']}점"
        for r in rubric_dicts
    )
    json_format = (
        '{"rubric_scores": [{"item": "소항목명", "score": 정수, "maxScore": 정수}, ...], '
        '"total_score": 정수, "feedback": "피드백 문자열"}'
    )

    system_prompt = (
        "당신은 IT 교육 과정의 능력단위평가 채점 AI입니다. "
        "루브릭 각 항목별로 점수를 부여하고 "
        "반드시 아래 JSON 형식으로만 응답하세요:\n"
        f"{json_format}\n"
        "⚠️ 제출 내용이 없거나 평가와 무관한 경우 엄격하게 0점을 부여하세요. "
        "제출 내용 없이 점수를 추측하지 마세요."
    )

    # 제출 파일 텍스트 추출 — 제출됐지만 읽을 수 없는 파일도 추적
    file_content_text = ""
    submitted_names: list[str] = []
    unreadable_names: list[str] = []
    if file_items:
        import httpx
        texts = []
        text_exts = {".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css",
                     ".java", ".sql", ".md", ".txt", ".json", ".yaml", ".yml"}
        for original_name, url in file_items:
            submitted_names.append(original_name)
            ext = original_name[original_name.rfind("."):].lower() if "." in original_name else ""
            if ext not in text_exts:
                unreadable_names.append(original_name)
                continue
            try:
                async with httpx.AsyncClient(timeout=10) as http:
                    resp = await http.get(url)
                    texts.append(f"### {original_name}\n{resp.text[:3000]}")
            except Exception:
                unreadable_names.append(original_name)
        if texts:
            file_content_text = "\n\n".join(texts)

    # 파일이 제출됐지만 텍스트로 읽을 수 없으면 → GPT 호출 없이 0점 반환
    if submitted_names and not file_content_text:
        fallback = [{"item": r["item"], "score": 0, "maxScore": r["maxScore"]} for r in rubric_dicts]
        names_str = ", ".join(submitted_names)
        feedback = (
            f"제출된 파일({names_str})은 텍스트로 읽을 수 없는 형식입니다 "
            f"(이미지·압축파일·PDF·바이너리 등). "
            f"코드/텍스트 파일(.py, .js, .html 등)을 제출해야 AI 채점이 가능합니다."
        )
        return {"score": 0, "rubric_scores": fallback, "feedback": feedback}

    # 일부 파일이 읽기 불가 — 프롬프트에 명시
    unreadable_note = ""
    if unreadable_names:
        unreadable_note = f"\n(읽기 불가 파일: {', '.join(unreadable_names)} — 이진 형식)\n"

    content_section = (
        f"학생 제출 코드/내용:\n{file_content_text}{unreadable_note}\n\n"
        if file_content_text
        else "⚠️ 제출된 파일 없음. 학생이 아무것도 제출하지 않았으므로 모든 항목 0점으로 채점하세요.\n\n"
    )

    user_prompt = (
        f"평가 설명:\n{assessment_description}\n\n"
        f"루브릭 (각 항목별 최대 점수):\n{rubric_text}\n\n"
        f"전체 최대 점수: {max_score}\n\n"
        + content_section
        + "위 기준으로 루브릭 항목별 점수와 종합 피드백을 제시해주세요."
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
            max_tokens=800,
        )
        import json

        result = json.loads(response.choices[0].message.content)
        raw_rubric_scores = result.get("rubric_scores") or []

        # maxScore 보완 + 점수 범위 보정
        max_map = {r["item"]: r["maxScore"] for r in rubric_dicts}
        rubric_scores = []
        for rs in raw_rubric_scores:
            item = rs.get("item", "")
            ms = rs.get("maxScore") or max_map.get(item, 0)
            rubric_scores.append({
                "item": item,
                "score": min(int(rs.get("score", 0)), ms),
                "maxScore": ms,
            })

        # GPT가 누락한 항목 보완
        returned = {rs["item"] for rs in rubric_scores}
        for r in rubric_dicts:
            if r["item"] not in returned:
                rubric_scores.append({"item": r["item"], "score": 0, "maxScore": r["maxScore"]})

        total = min(sum(rs["score"] for rs in rubric_scores), max_score)

        return {
            "score": int(result.get("total_score", total)),
            "rubric_scores": rubric_scores,
            "feedback": str(result.get("feedback", "")),
        }
    except Exception:
        fallback = [{"item": r["item"], "score": 0, "maxScore": r["maxScore"]} for r in rubric_dicts]
        return {
            "score": 0,
            "rubric_scores": fallback,
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
            model="gpt-5.4-nano-2026-03-17",
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


# 텍스트로 읽을 수 있는 파일 확장자
_TEXT_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp", ".cs",
    ".html", ".css", ".scss", ".json", ".md", ".txt", ".sql", ".sh",
    ".yaml", ".yml", ".xml", ".go", ".rs", ".rb", ".php",
}


async def _fetch_file_text(url: str, max_chars: int = 3000) -> str | None:
    """URL에서 텍스트 파일 내용을 가져온다. 바이너리/비텍스트면 None 반환."""
    import httpx
    from pathlib import PurePosixPath

    path = PurePosixPath(url.split("?")[0])
    if path.suffix.lower() not in _TEXT_EXTENSIONS:
        return None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            text = resp.text
            return text[:max_chars] + ("..." if len(text) > max_chars else "")
    except Exception:
        return None


async def grade_assignment_submission(
    assignment_title: str,
    assignment_description: str,
    rubric: list,
    file_items: list[tuple[str, str]],  # (원본 파일명, signed URL) 쌍
) -> dict:
    """과제 제출물(파일)을 루브릭 기반으로 AI 채점.

    file_items: [(원본 파일명, URL), ...] — Supabase Storage signed URL
    Returns:
        {
          "rubric_scores": [{"item": str, "score": int, "maxScore": int}],
          "feedback": str
        }
    """
    import json as _json

    client = _get_client()

    # 파일 내용 수집 — 원본 파일명을 사용해 GPT에 의미있는 컨텍스트 제공
    file_contents: list[str] = []
    for original_name, url in file_items:
        content = await _fetch_file_text(url)
        if content:
            file_contents.append(f"=== 파일: {original_name} ===\n{content}")

    has_files = bool(file_contents)
    files_section = (
        "\n\n".join(file_contents)
        if has_files
        else "※ 제출된 텍스트 파일이 없습니다. 과제 정보와 루브릭만으로 평가해주세요."
    )

    # 루브릭 JSON 구조 및 점수 범위
    rubric_schema = _json.dumps(
        [{"item": r.get("item", ""), "maxScore": r.get("maxScore", 0)} for r in rubric if isinstance(r, dict)],
        ensure_ascii=False,
    )

    system_prompt = (
        "당신은 IT 교육 과정의 과제 채점 전문 AI입니다. "
        "학생이 제출한 파일을 읽고 루브릭 각 항목별로 점수를 매기고 종합 피드백을 작성합니다.\n"
        "반드시 아래 JSON 형식으로만 응답하세요:\n"
        '{"rubric_scores": [{"item": "항목명", "score": 실제점수}], "feedback": "종합 피드백"}\n'
        "각 항목의 score는 0 이상 maxScore 이하의 정수여야 합니다. "
        "파일이 없거나 내용과 과제가 무관하면 낮은 점수를 부여하세요."
    )

    user_prompt = (
        f"과제 제목: {assignment_title}\n"
        f"과제 설명: {assignment_description}\n\n"
        f"루브릭:\n{rubric_schema}\n\n"
        f"제출 파일 내용:\n{files_section}"
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
            max_tokens=800,
        )
        result = _json.loads(response.choices[0].message.content)

        # 루브릭 스코어 정규화 (maxScore 초과 방지)
        raw_scores: list[dict] = result.get("rubric_scores", [])
        normalized = []
        for r in rubric:
            if not isinstance(r, dict):
                continue
            item = r.get("item", "")
            max_s = r.get("maxScore") or 0
            matched = next((s for s in raw_scores if s.get("item") == item), None)
            score = int(matched.get("score", 0)) if matched else 0
            normalized.append({"item": item, "score": min(score, max_s), "maxScore": max_s})

        total = sum(s["score"] for s in normalized)
        return {
            "rubric_scores": normalized,
            "total_score": total,
            "feedback": str(result.get("feedback", "")),
        }
    except Exception:
        # 실패 시 0점 반환
        normalized = [
            {"item": r.get("item", ""), "score": 0, "maxScore": r.get("maxScore", 0)}
            for r in rubric if isinstance(r, dict)
        ]
        return {
            "rubric_scores": normalized,
            "total_score": 0,
            "feedback": "AI 채점 중 오류가 발생했습니다. 직접 채점해 주세요.",
        }


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
