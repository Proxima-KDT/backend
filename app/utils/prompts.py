COMPANY_CONTEXT = {
    "naver": "네이버(NAVER) - 국내 최대 검색/AI/클라우드 플랫폼 기업. 대규모 트래픽 처리, 분산 시스템, NCP(네이버 클라우드), 데이터 엔지니어링 역량을 중시합니다.",
    "kakao": "카카오(Kakao) - 카카오톡 기반 플랫폼/핀테크/콘텐츠 기업. MSA 아키텍처, 고가용성 서비스 설계, Kotlin/Java, 데이터 기반 의사결정을 중시합니다.",
    "line": "라인(LINE) - 글로벌 메신저 플랫폼. 글로벌 서비스 개발 경험, Java/Spring Boot, 다국어·다시간대 서비스 운영, 데이터 파이프라인 역량을 중시합니다.",
    "coupang": "쿠팡(Coupang) - 이커머스/물류 테크 기업. 대규모 주문·재고 시스템, Java/Kotlin, MSA, AWS 인프라, 고성능 API 설계 역량을 중시합니다.",
    "samsung_sds": "삼성SDS - 대기업 IT서비스/클라우드. Java/Spring, 엔터프라이즈 아키텍처, 보안, SI 프로젝트 관리 역량을 중시합니다.",
    "lg_cns": "LG CNS - IT서비스/DX 전문 기업. Java/Spring, 클라우드 전환, 스마트팩토리·물류 시스템, 엔터프라이즈 솔루션 역량을 중시합니다.",
    "sk_telecom": "SK텔레콤 - 통신/AI/클라우드 기업. 5G/AI 서비스 개발, Python/ML, 네트워크 기반 서비스, 데이터 분석 역량을 중시합니다.",
    "toss": "토스(Toss/Viva Republica) - 핀테크 유니콘. React/Kotlin, 금융 도메인 이해, 보안·인증 시스템, 빠른 실행력과 사용자 중심 개발을 중시합니다.",
    "kakaobank": "카카오뱅크 - 인터넷전문은행. Java/Spring Boot, 금융 규정 준수, 핀테크 보안, 대용량 트랜잭션 처리 역량을 중시합니다.",
    "startup": "스타트업(일반) - 빠른 제품 개발과 자기 주도 능력, 풀스택 역량, 린(Lean) 방법론, 주인의식을 중시합니다.",
}

POSITION_CONTEXT = {
    "frontend": "프론트엔드 개발자 - React, TypeScript, 상태 관리, 성능 최적화, 접근성, 크로스 브라우저 호환성, 웹 표준 역량을 평가합니다.",
    "backend": "백엔드 개발자 - RESTful API 설계, 데이터베이스 설계/최적화, 서버 아키텍처, 보안, 인증/인가, 캐싱 역량을 평가합니다.",
    "fullstack": "풀스택 개발자 - 프론트·백엔드 전반 역량, 전체 개발 사이클 이해, 시스템 설계, 배포 자동화 역량을 평가합니다.",
    "data_engineer": "데이터 엔지니어 - ETL 파이프라인, SQL/NoSQL, Spark/Kafka 등 빅데이터 처리, 데이터 모델링 역량을 평가합니다.",
    "devops": "DevOps/클라우드 엔지니어 - CI/CD, Docker/Kubernetes, 클라우드(AWS/GCP), 모니터링, 인프라 코드화(IaC) 역량을 평가합니다.",
    "mobile": "모바일 개발자 - Android(Kotlin)/iOS(Swift) 또는 React Native/Flutter, 모바일 UX, 성능 최적화, 앱 배포 역량을 평가합니다.",
}

INTERVIEW_TYPE_CONTEXT = {
    "technical": "기술 면접 - 지원자의 기술적 역량, CS 기초(자료구조·알고리즘·OS·네트워크), 실무 경험, 문제 해결 능력을 집중 평가합니다.",
    "personality": "인성 면접 - 지원자의 가치관, 팀워크, 커뮤니케이션, 성장 마인드셋, 위기 대처 능력을 평가합니다.",
    "mixed": "복합 면접 - 기술 역량(50%)과 인성·문화 적합성(50%)을 균형 있게 평가합니다.",
}


def get_interview_system_prompt(company: str, position: str, interview_type: str) -> str:
    company_ctx = COMPANY_CONTEXT.get(company, f"{company} 기업")
    position_ctx = POSITION_CONTEXT.get(position, f"{position}")
    type_ctx = INTERVIEW_TYPE_CONTEXT.get(interview_type, "")

    return f"""당신은 {company_ctx.split(' - ')[0]} 소속의 전문 면접관입니다.
이 면접은 아래에 명시된 포지션 지원자를 평가하기 위한 면접입니다.

[회사 정보]
{company_ctx}

[지원 포지션] ← 이 포지션에 맞는 질문만 하세요
{position_ctx}

[면접 유형]
{type_ctx}

[면접 진행 규칙]
- 반드시 한국어로 진행하세요.
- 질문은 간결하고 명확하게 1개씩만 하세요. (최대 2~3문장)
- 전체 5개 질문으로 면접을 구성하세요.
- 첫 번째 질문은 반드시 자기소개로 시작하세요.
- 답변을 평가할 때는 기술 정확성, 구체성, 소통 능력을 종합 고려하세요.
- 압박 면접이 아닌 편안하고 전문적인 분위기를 유지하세요.

[질문 방향 — 반드시 준수]
- 질문은 반드시 위 [지원 포지션] 역량 범위 안에서만 출제하세요.
- 지원자가 자기소개에서 언급한 관심 분야·기술·경험을 파악하고, 이어지는 질문에서 그 내용을 구체적으로 파고드세요.
- 지원 포지션과 무관한 다른 직군(예: 프론트엔드 포지션 지원자에게 백엔드 질문, 백엔드 지원자에게 프론트엔드 질문)은 절대 묻지 마세요.
- 지원자가 언급하지 않은 기술 스택이나 경험을 임의로 가정하지 마세요.
"""


def get_report_prompt(company: str, position: str, interview_type: str, qa_pairs: list) -> str:
    qa_text = "\n".join([
        f"Q{i+1}: {pair['question']}\nA{i+1}: {pair['answer']}"
        for i, pair in enumerate(qa_pairs)
    ])

    return f"""다음은 {company} {position} {interview_type} 모의면접 전체 내용입니다.

{qa_text}

위 면접 내용을 바탕으로 다음 JSON 형식으로 평가 리포트를 작성해주세요:
{{
  "total_score": <0~100 정수>,
  "categories": [
    {{"name": "기술 지식", "score": <0~100>}},
    {{"name": "문제 해결", "score": <0~100>}},
    {{"name": "커뮤니케이션", "score": <0~100>}},
    {{"name": "논리적 사고", "score": <0~100>}}
  ],
  "summary": "<아래 구성을 모두 포함한 8~12문장의 상세 총평. ① 지원자의 전반적인 인상과 강점 2~3가지를 구체적으로 서술, ② 각 질문 답변에서 드러난 특징적인 점(잘한 부분·아쉬운 부분)을 2~3문장으로 언급, ③ 포지션 적합도와 성장 가능성에 대한 평가 1~2문장, ④ 최종 합격 가능성 또는 보완이 필요한 핵심 역량에 대한 총괄 의견 1~2문장으로 마무리>",
  "improvements": [
    "<개선 포인트 1: 구체적인 상황과 함께 어떻게 개선해야 하는지 서술>",
    "<개선 포인트 2: 구체적인 상황과 함께 어떻게 개선해야 하는지 서술>",
    "<개선 포인트 3: 구체적인 상황과 함께 어떻게 개선해야 하는지 서술>"
  ]
}}

JSON만 반환하세요. 다른 텍스트는 포함하지 마세요."""
