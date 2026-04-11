"""통합 AI 에이전트 라우터.

엔드포인트:
- POST /api/ai-agent/chat                           — Path A (Direct SDK Q&A)
- POST /api/ai-agent/workflow/{name}                — Path B (LangGraph workflow 시작)
- POST /api/ai-agent/workflow/resume/{thread_id}    — Path B 재개 (human-in-the-loop)
- GET  /api/ai-agent/summary                        — 사이드 패널 요약 (AI 호출 없음)

Phase B 단계에서는 모든 핸들러가 서비스 stub 을 호출해 200 을 반환한다.
이 상태로 Docker 빌드 / EC2 배포 / Nginx 프록시까지 전체 파이프라인을 먼저 검증한다.
Phase 2~3 에서 서비스 내부를 채우면 엔드포인트는 그대로 유지된다.
"""

from fastapi import APIRouter, Depends

from app.dependencies import get_current_user
from app.schemas.ai_agent import (
    AgentChatRequest,
    AgentChatResponse,
    AgentSummaryResponse,
    WorkflowRequest,
    WorkflowResponse,
    WorkflowResumeRequest,
)
from app.services import ai_agent_service

router = APIRouter(prefix="/api/ai-agent", tags=["ai-agent"])


@router.post("/chat", response_model=AgentChatResponse)
async def chat(
    body: AgentChatRequest,
    user: dict = Depends(get_current_user),
) -> AgentChatResponse:
    """Path A: 단일 턴 Function Calling 기반 Q&A."""
    history_raw = [m.model_dump() for m in body.history] if body.history else None
    result = await ai_agent_service.run_direct(user, body.message, history_raw)
    return AgentChatResponse(**result)


@router.post("/workflow/{name}", response_model=WorkflowResponse)
async def run_workflow(
    name: str,
    body: WorkflowRequest,
    user: dict = Depends(get_current_user),
) -> WorkflowResponse:
    """Path B: LangGraph workflow 실행.

    LangGraph 서비스는 첫 요청 시에만 import 되어 FastAPI 콜드스타트 영향을 줄인다.
    """
    from app.services import ai_agent_workflow  # noqa: PLC0415 (지연 import 의도적)

    result = await ai_agent_workflow.run(name, user, body.params or {})
    return WorkflowResponse(**result)


@router.post("/workflow/resume/{thread_id}", response_model=WorkflowResponse)
async def resume_workflow(
    thread_id: str,
    body: WorkflowResumeRequest,
    user: dict = Depends(get_current_user),
) -> WorkflowResponse:
    """interrupt 된 workflow 재개 — proactive_risk_alert 승인/거절용."""
    from app.services import ai_agent_workflow  # noqa: PLC0415

    result = await ai_agent_workflow.resume(thread_id, user, body.model_dump())
    return WorkflowResponse(**result)


@router.get("/summary", response_model=AgentSummaryResponse)
async def summary(
    user: dict = Depends(get_current_user),
) -> AgentSummaryResponse:
    """사이드 패널 초기 로드용 요약 카드. AI 호출 없이 고정 쿼리."""
    result = await ai_agent_service.get_role_summary(user)
    return AgentSummaryResponse(**result)
