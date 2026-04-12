"""통합 AI 에이전트 Pydantic 스키마.

Path A (Direct SDK Q&A) 와 Path B (LangGraph workflow) 를 모두 커버한다.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field


# ============================================================
# Path A: Direct SDK Function Calling 채팅
# ============================================================


class ChatMessage(BaseModel):
    """세션 내 대화 턴 1개 — OpenAI messages 배열과 호환되는 최소 필드."""

    role: Literal["user", "assistant", "system", "tool"]
    content: str


class AgentChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    history: list[ChatMessage] | None = None  # 세션 내 이전 대화 (최대 10턴 권장)


class ToolCallRecord(BaseModel):
    """AI가 호출한 tool 1건의 간결한 기록 (agent_logs.tool_calls 에 저장)."""

    name: str
    args: dict[str, Any] = {}
    result_preview: str | None = None  # 500자 이내 요약


class AgentChatResponse(BaseModel):
    answer: str
    tool_calls: list[ToolCallRecord] = []
    duration_ms: int
    path: Literal["direct", "workflow"] = "direct"


# ============================================================
# Path B: LangGraph Workflow
# ============================================================


class WorkflowRequest(BaseModel):
    params: dict[str, Any] | None = None


class WorkflowTraceNode(BaseModel):
    """graph 노드 실행 1건 — 발표/디버깅용 trace."""

    node: str
    duration_ms: int | None = None
    keys: list[str] = []


class WorkflowResponse(BaseModel):
    result: dict[str, Any]
    graph_trace: list[WorkflowTraceNode] = []
    duration_ms: int
    thread_id: str
    # proactive_risk_alert 같은 human-in-the-loop workflow 가 중단 상태일 때 true
    interrupted: bool = False


class WorkflowResumeRequest(BaseModel):
    """interrupt 된 workflow 재개용."""

    approved: bool
    edits: dict[str, Any] | None = None  # 사용자가 초안을 수정했을 경우


# ============================================================
# 사이드 패널 요약 (AI 호출 없음 — 고정 쿼리)
# ============================================================


class SummaryCard(BaseModel):
    title: str
    value: str
    sub: str | None = None
    icon: str | None = None
    color: str | None = None  # tailwind 색 hint (e.g., "emerald", "rose")


class AgentSummaryResponse(BaseModel):
    role: Literal["student", "teacher", "admin"]
    cards: list[SummaryCard] = []


# ============================================================
# 대화 이력 조회
# ============================================================


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    tool_calls: list[ToolCallRecord] = []
    duration_ms: int | None = None


class ChatHistoryResponse(BaseModel):
    messages: list[HistoryMessage]
    total: int
