"""Path B: LangGraph StateGraph 기반 workflow 3종.

- teacher_daily_briefing: 강사 일일 브리핑
    병렬 수집 (출석/과제 제출) → 위험 분석 → (위험≥3?) conditional → 종합 요약 → END
- admin_weekly_report: 관리자 주간 운영 리포트
    병렬 수집 (코호트/장비/강의실/경고) → 종합 리포트 작성 → END
- proactive_risk_alert: 능동 알림 (human-in-the-loop)
    위험 감지 → 알림 초안 → interrupt (사용자 승인 대기) → resume 시 agent_notifications insert → END

LangGraph 모듈은 파일 top-level 에서 import 하지만, 라우터가 이 모듈을
'첫 요청 시에만' 지연 import 하므로 FastAPI 콜드스타트 영향은 제한적이다.
Graph 빌드/컴파일은 지연 패턴으로 더 뒤로 밀어둔다.

Tool 구현은 ai_agent_service.py 의 _tool_* 함수들을 재사용한다
(중복 쿼리 회피 + RBAC 일관성 유지).
"""

from __future__ import annotations

import logging
import time
from operator import add
from typing import Annotated, Any, TypedDict

from fastapi import HTTPException
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.services.ai_agent_service import (
    MAX_TOKENS,
    MODEL_NAME,
    TEMPERATURE,
    _get_client,
    _tool_get_assignment_submission_stats,
    _tool_get_at_risk_students,
    _tool_get_class_attendance_summary,
    _tool_get_cohort_progress,
    _tool_get_equipment_status,
    _tool_get_global_alerts,
    _tool_get_room_utilization,
)
from app.utils.supabase_client import get_supabase

logger = logging.getLogger(__name__)


# ============================================================
# 공통: workflow 메타, checkpointer, LLM 요약 헬퍼
# ============================================================

# 각 workflow 가 어떤 role 을 요구하는지 (RBAC 가드)
# admin 은 모든 workflow 실행 가능 (운영자 특권).
_KNOWN_WORKFLOWS: dict[str, str] = {
    "teacher_daily_briefing": "teacher",
    "admin_weekly_report": "admin",
    "proactive_risk_alert": "teacher",
}

# 프로세스 생애주기 동안 공유되는 MemorySaver.
# 같은 thread_id 로 resume 하려면 동일 인스턴스여야 한다.
_shared_saver: MemorySaver | None = None


def _get_saver() -> MemorySaver:
    global _shared_saver
    if _shared_saver is None:
        _shared_saver = MemorySaver()
    return _shared_saver


async def _summarize_with_llm(system_prompt: str, user_content: str) -> str:
    """OpenAI gpt-4o-mini 로 요약 텍스트 1회 생성 (tool 사용 없음)."""
    client = _get_client()
    try:
        response = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
        )
        return (response.choices[0].message.content or "").strip()
    except Exception as e:
        logger.exception("LLM 요약 호출 실패")
        return f"(요약 생성 실패: {type(e).__name__})"


def _trace_entry(node: str, started_at: float, **extra) -> dict:
    """graph_trace 용 엔트리 한 건."""
    entry = {
        "node": node,
        "duration_ms": int((time.monotonic() - started_at) * 1000),
    }
    entry.update(extra)
    return entry


# ============================================================
# ============================================================
# Workflow 1: teacher_daily_briefing
# ============================================================
# ============================================================


class BriefingState(TypedDict, total=False):
    user: dict
    params: dict

    # 병렬 수집 결과
    attendance: dict
    assignments: dict

    # 분석 결과
    risk: dict

    # 종합
    summary: str
    suggested_notifications: list[dict]

    # 노드 실행 trace (reducer 로 concat)
    trace: Annotated[list[dict], add]


def node_briefing_collect_attendance(state: BriefingState) -> dict:
    """오늘/이번주 클래스 출석 요약 수집 (선택 과정 필터 적용)."""
    started = time.monotonic()
    user = state["user"]
    params = state.get("params") or {}
    tool_args: dict = {"period": "week"}
    if params.get("course_id"):
        tool_args["course_id"] = params["course_id"]
    try:
        att = _tool_get_class_attendance_summary(tool_args, user)
    except Exception as e:
        logger.exception("collect_attendance 실패")
        att = {"error": str(e)}
    return {
        "attendance": att,
        "trace": [_trace_entry("collect_attendance", started, keys=list(att.keys()))],
    }


def node_briefing_collect_assignments(state: BriefingState) -> dict:
    """최근 과제 제출 통계 수집."""
    started = time.monotonic()
    user = state["user"]
    try:
        asg = _tool_get_assignment_submission_stats({}, user)
    except Exception as e:
        logger.exception("collect_assignments 실패")
        asg = {"error": str(e)}
    return {
        "assignments": asg,
        "trace": [_trace_entry("collect_assignments", started, keys=list(asg.keys()))],
    }


def node_briefing_analyze_risk(state: BriefingState) -> dict:
    """위험 학생 식별 — _tool_get_at_risk_students 호출 (선택 과정 필터 적용)."""
    started = time.monotonic()
    user = state["user"]
    params = state.get("params") or {}
    threshold = int(params.get("threshold_pct", 80))
    tool_args: dict = {"threshold_pct": threshold, "limit": 10}
    if params.get("course_id"):
        tool_args["course_id"] = params["course_id"]
    try:
        risk = _tool_get_at_risk_students(tool_args, user)
    except Exception as e:
        logger.exception("analyze_risk 실패")
        risk = {"count": 0, "students": [], "error": str(e)}
    return {
        "risk": risk,
        "trace": [
            _trace_entry(
                "analyze_risk",
                started,
                at_risk_count=risk.get("count", 0),
            )
        ],
    }


def route_after_risk(state: BriefingState) -> str:
    """conditional_edge: 위험 학생 3명 이상이면 알림 제안 노드로, 아니면 바로 요약."""
    risk_count = len(state.get("risk", {}).get("students", []))
    if risk_count >= 3:
        return "suggest_alerts"
    return "summarize"


def node_briefing_suggest_alerts(state: BriefingState) -> dict:
    """위험 학생에게 보낼 알림 초안 생성 (실제 발송은 안 함)."""
    started = time.monotonic()
    risk = state.get("risk", {})
    drafts: list[dict] = []
    for s in risk.get("students", [])[:5]:
        drafts.append(
            {
                "student_id": s.get("student_id"),
                "student_name": s.get("name"),
                "severity": "high" if s.get("attendance_rate_pct", 100) < 60 else "medium",
                "title": "출석 경고",
                "message": (
                    f"{s.get('name')}님의 최근 30일 출석률이 "
                    f"{s.get('attendance_rate_pct')}% 입니다. 상담이 필요할 수 있습니다."
                ),
            }
        )
    return {
        "suggested_notifications": drafts,
        "trace": [_trace_entry("suggest_alerts", started, draft_count=len(drafts))],
    }


async def node_briefing_summarize(state: BriefingState) -> dict:
    """수집된 데이터를 기반으로 강사용 브리핑 텍스트를 LLM 으로 생성."""
    started = time.monotonic()
    att = state.get("attendance", {})
    asg = state.get("assignments", {})
    risk = state.get("risk", {})
    drafts = state.get("suggested_notifications", [])

    system = (
        "당신은 EduPilot 의 강사용 일일 브리핑 작성자입니다. "
        "제공된 데이터를 기반으로 400자 이내의 한국어 브리핑을 작성하세요. "
        "규칙: "
        "1) 학생 이름을 반드시 실명으로 명시하세요. '일부 학생' 같은 모호한 표현 금지. "
        "2) 과제는 제목(title)을 명시하세요. '일부 과제' 같은 표현 금지. "
        "3) 수치는 구체적으로(예: 출석률 70.0%, 결석 3회). "
        "4) 중요도 순으로 bullet 4~5개. "
        "5) 추측·예측 금지, 데이터에 없는 내용 작성 금지."
    )
    user_content = (
        f"[출석 요약 - 이번 주]\n{att}\n\n"
        f"[과제 제출 통계 - 최근 과제 목록 포함]\n{asg}\n\n"
        f"[위험 학생 - 출석률 미달 학생]\n{risk}\n\n"
        f"[초안 알림 {len(drafts)}건]\n{drafts}"
    )
    summary = await _summarize_with_llm(system, user_content)
    return {
        "summary": summary,
        "trace": [_trace_entry("summarize", started, summary_len=len(summary))],
    }


_teacher_briefing_graph = None


def get_teacher_briefing_graph():
    """지연 빌드 — 첫 호출 시에만 StateGraph 컴파일."""
    global _teacher_briefing_graph
    if _teacher_briefing_graph is not None:
        return _teacher_briefing_graph

    g: StateGraph = StateGraph(BriefingState)
    g.add_node("collect_attendance", node_briefing_collect_attendance)
    g.add_node("collect_assignments", node_briefing_collect_assignments)
    g.add_node("analyze_risk", node_briefing_analyze_risk)
    g.add_node("suggest_alerts", node_briefing_suggest_alerts)
    g.add_node("summarize", node_briefing_summarize)

    # 병렬 fan-out: START → 두 수집 노드
    g.add_edge(START, "collect_attendance")
    g.add_edge(START, "collect_assignments")

    # fan-in: 두 수집 노드가 모두 끝나면 analyze_risk 실행
    g.add_edge("collect_attendance", "analyze_risk")
    g.add_edge("collect_assignments", "analyze_risk")

    # conditional branch
    g.add_conditional_edges(
        "analyze_risk",
        route_after_risk,
        {"suggest_alerts": "suggest_alerts", "summarize": "summarize"},
    )
    g.add_edge("suggest_alerts", "summarize")
    g.add_edge("summarize", END)

    _teacher_briefing_graph = g.compile(checkpointer=_get_saver())
    return _teacher_briefing_graph


# ============================================================
# ============================================================
# Workflow 2: admin_weekly_report
# ============================================================
# ============================================================


class WeeklyReportState(TypedDict, total=False):
    user: dict
    params: dict

    # 병렬 수집
    cohort_progress: dict
    equipment_status: dict
    room_utilization: dict
    global_alerts: dict

    # 종합
    summary: str

    trace: Annotated[list[dict], add]


def node_report_collect_cohort(state: WeeklyReportState) -> dict:
    started = time.monotonic()
    user = state["user"]
    try:
        data = _tool_get_cohort_progress({}, user)
    except Exception as e:
        data = {"count": 0, "cohorts": [], "error": str(e)}
    return {
        "cohort_progress": data,
        "trace": [_trace_entry("collect_cohort_progress", started, count=data.get("count", 0))],
    }


def node_report_collect_equipment(state: WeeklyReportState) -> dict:
    started = time.monotonic()
    user = state["user"]
    try:
        data = _tool_get_equipment_status({}, user)
    except Exception as e:
        data = {"total": 0, "by_status": {}, "error": str(e)}
    return {
        "equipment_status": data,
        "trace": [_trace_entry("collect_equipment", started, total=data.get("total", 0))],
    }


def node_report_collect_rooms(state: WeeklyReportState) -> dict:
    started = time.monotonic()
    user = state["user"]
    try:
        data = _tool_get_room_utilization({}, user)
    except Exception as e:
        data = {"total_reservations": 0, "by_room": [], "error": str(e)}
    return {
        "room_utilization": data,
        "trace": [
            _trace_entry(
                "collect_rooms",
                started,
                reservations=data.get("total_reservations", 0),
            )
        ],
    }


def node_report_collect_alerts(state: WeeklyReportState) -> dict:
    started = time.monotonic()
    user = state["user"]
    try:
        data = _tool_get_global_alerts({"limit": 10}, user)
    except Exception as e:
        data = {"count": 0, "alerts": [], "error": str(e)}
    return {
        "global_alerts": data,
        "trace": [_trace_entry("collect_alerts", started, count=data.get("count", 0))],
    }


async def node_report_synthesize(state: WeeklyReportState) -> dict:
    started = time.monotonic()
    cohort = state.get("cohort_progress", {})
    equip = state.get("equipment_status", {})
    rooms = state.get("room_utilization", {})
    alerts = state.get("global_alerts", {})

    system = (
        "당신은 EduPilot 의 운영 주간 리포트 작성자입니다. "
        "제공된 코호트/장비/강의실/경고 데이터를 종합해 관리자용 주간 리포트를 작성하세요. "
        "형식: [요약 1~2줄] → [핵심 수치 bullet 4~5개] → [이상 징후 및 권장 조치]. "
        "한국어 경어체, 500자 이내, 추측 금지."
    )
    user_content = (
        f"[진행 중 코호트]\n{cohort}\n\n"
        f"[장비 현황]\n{equip}\n\n"
        f"[오늘 강의실 예약]\n{rooms}\n\n"
        f"[시스템 경고 최근 10건]\n{alerts}"
    )
    summary = await _summarize_with_llm(system, user_content)
    return {
        "summary": summary,
        "trace": [_trace_entry("synthesize_report", started, summary_len=len(summary))],
    }


_admin_report_graph = None


def get_admin_report_graph():
    global _admin_report_graph
    if _admin_report_graph is not None:
        return _admin_report_graph

    g: StateGraph = StateGraph(WeeklyReportState)
    g.add_node("collect_cohort", node_report_collect_cohort)
    g.add_node("collect_equipment", node_report_collect_equipment)
    g.add_node("collect_rooms", node_report_collect_rooms)
    g.add_node("collect_alerts", node_report_collect_alerts)
    g.add_node("synthesize", node_report_synthesize)

    # 4-way 병렬 fan-out
    g.add_edge(START, "collect_cohort")
    g.add_edge(START, "collect_equipment")
    g.add_edge(START, "collect_rooms")
    g.add_edge(START, "collect_alerts")

    # 전부 synthesize 로 fan-in
    g.add_edge("collect_cohort", "synthesize")
    g.add_edge("collect_equipment", "synthesize")
    g.add_edge("collect_rooms", "synthesize")
    g.add_edge("collect_alerts", "synthesize")

    g.add_edge("synthesize", END)

    _admin_report_graph = g.compile(checkpointer=_get_saver())
    return _admin_report_graph


# ============================================================
# ============================================================
# Workflow 3: proactive_risk_alert (human-in-the-loop)
# ============================================================
# ============================================================


class ProactiveAlertState(TypedDict, total=False):
    user: dict
    params: dict

    detected: dict           # 위험 감지 결과
    draft_notifications: list[dict]    # 초안 알림 목록 (사용자 승인 대상)
    sent_ids: list[int]      # agent_notifications insert 결과 ID

    trace: Annotated[list[dict], add]


def node_proactive_detect_risk(state: ProactiveAlertState) -> dict:
    """위험 학생 탐지 — teacher 의 at_risk_students tool 재사용."""
    started = time.monotonic()
    user = state["user"]
    params = state.get("params") or {}
    threshold = int(params.get("threshold_pct", 70))  # 능동 알림은 더 엄격
    try:
        risk = _tool_get_at_risk_students(
            {"threshold_pct": threshold, "limit": 10}, user
        )
    except Exception as e:
        logger.exception("proactive detect_risk 실패")
        risk = {"count": 0, "students": [], "error": str(e)}
    return {
        "detected": risk,
        "trace": [_trace_entry("detect_risk", started, count=risk.get("count", 0))],
    }


def node_proactive_draft_notifications(state: ProactiveAlertState) -> dict:
    """위험 학생별로 알림 초안 작성. 이후 interrupt 로 사용자 승인 대기."""
    started = time.monotonic()
    detected = state.get("detected", {})
    students = detected.get("students", [])
    drafts: list[dict] = []
    for s in students:
        rate = s.get("attendance_rate_pct", 100)
        drafts.append(
            {
                "student_id": s.get("student_id"),
                "student_name": s.get("name"),
                "severity": "high" if rate < 60 else "medium",
                "title": "학습 경고: 출석률 저하",
                "message": (
                    f"안녕하세요 {s.get('name')}님. "
                    f"최근 30일 출석률이 {rate}%로 기준치(70%)에 미달합니다. "
                    f"담당 강사와 상담을 권유드립니다."
                ),
                "agent_type": "proactive_risk_alert",
            }
        )
    return {
        "draft_notifications": drafts,
        "trace": [
            _trace_entry(
                "draft_notifications",
                started,
                draft_count=len(drafts),
                waiting_for_approval=True,
            )
        ],
    }


def node_proactive_send_notifications(state: ProactiveAlertState) -> dict:
    """사용자 승인 후 재개 시 실행. agent_notifications 테이블에 실제 insert.

    이 노드는 interrupt_before 목록에 있으므로 최초 실행에는 호출되지 않고,
    resume 단계에서만 실행된다.
    """
    started = time.monotonic()
    drafts = state.get("draft_notifications", [])
    sent_ids: list[int] = []

    if not drafts:
        return {
            "sent_ids": [],
            "trace": [_trace_entry("send_notifications", started, sent=0, skipped=True)],
        }

    supabase = get_supabase()
    for d in drafts:
        if not d.get("student_id"):
            continue
        payload = {
            "user_id": d["student_id"],
            "agent_type": d.get("agent_type", "proactive_risk_alert"),
            "severity": d.get("severity", "medium"),
            "title": d.get("title", "알림"),
            "message": d.get("message", ""),
            "payload": {"source": "proactive_risk_alert"},
        }
        try:
            res = supabase.table("agent_notifications").insert(payload).execute()
            if res.data:
                sent_ids.append(res.data[0].get("id"))
        except Exception as e:
            logger.warning("agent_notifications insert 실패 (student=%s): %s", d.get("student_id"), e)

    return {
        "sent_ids": sent_ids,
        "trace": [_trace_entry("send_notifications", started, sent=len(sent_ids))],
    }


_proactive_alert_graph = None


def get_proactive_alert_graph():
    global _proactive_alert_graph
    if _proactive_alert_graph is not None:
        return _proactive_alert_graph

    # 노드 이름은 state 키와 달라야 한다 (LangGraph 제약):
    #   - 'draft_notifications' 는 state 키로 이미 사용 중이므로 노드 이름은 'draft_alerts'
    #   - 'sent_ids' 는 state 키지만 노드 이름은 'send_alerts' 로 분리
    g: StateGraph = StateGraph(ProactiveAlertState)
    g.add_node("detect_risk", node_proactive_detect_risk)
    g.add_node("draft_alerts", node_proactive_draft_notifications)
    g.add_node("send_alerts", node_proactive_send_notifications)

    g.add_edge(START, "detect_risk")
    g.add_edge("detect_risk", "draft_alerts")
    g.add_edge("draft_alerts", "send_alerts")
    g.add_edge("send_alerts", END)

    # 핵심: send_alerts 직전에 사용자 승인을 위해 중단
    _proactive_alert_graph = g.compile(
        checkpointer=_get_saver(),
        interrupt_before=["send_alerts"],
    )
    return _proactive_alert_graph


# ============================================================
# 로깅 헬퍼 — workflow 1회 실행 결과를 agent_logs 에 기록
# ============================================================


def _log_workflow(
    user: dict,
    workflow_name: str,
    input_params: dict,
    result: dict | None,
    trace: list[dict],
    duration_ms: int,
    error: str | None,
) -> None:
    """workflow 로그 전용 wrapper. _log_to_supabase 를 재사용한다."""
    try:
        supabase = get_supabase()
        supabase.table("agent_logs").insert(
            {
                "agent_type": user.get("role") or "unknown",
                "trigger": f"workflow:{workflow_name}",
                "user_id": user.get("id"),
                "input": {"params": input_params, "workflow": workflow_name},
                "output": (
                    {
                        "summary": (result or {}).get("summary", ""),
                        "keys": list((result or {}).keys()),
                    }
                    if result is not None
                    else None
                ),
                "tool_calls": trace,
                "duration_ms": duration_ms,
                "error": error,
            }
        ).execute()
    except Exception as e:
        logger.warning("_log_workflow insert 실패 (무시): %s", e)


# ============================================================
# 메인 진입점 — run() / resume()
# ============================================================


async def run(name: str, user: dict, params: dict) -> dict[str, Any]:
    """Workflow 실행. 라우터에서 호출."""
    if name not in _KNOWN_WORKFLOWS:
        raise HTTPException(status_code=404, detail=f"Unknown workflow: {name}")

    required_role = _KNOWN_WORKFLOWS[name]
    user_role = user.get("role")
    if user_role != required_role and user_role != "admin":
        raise HTTPException(
            status_code=403,
            detail=f"'{name}' workflow 는 {required_role} 또는 admin 권한이 필요합니다.",
        )

    thread_id = f"{user['id']}-{int(time.time() * 1000)}"
    config = {"configurable": {"thread_id": thread_id}}
    initial_state: dict[str, Any] = {
        "user": user,
        "params": params,
        "trace": [],
    }

    start = time.monotonic()
    try:
        if name == "teacher_daily_briefing":
            graph = get_teacher_briefing_graph()
            final_state = await graph.ainvoke(initial_state, config)
            interrupted = False
        elif name == "admin_weekly_report":
            graph = get_admin_report_graph()
            final_state = await graph.ainvoke(initial_state, config)
            interrupted = False
        elif name == "proactive_risk_alert":
            graph = get_proactive_alert_graph()
            # interrupt_before=["send_notifications"] 때문에 draft 까지 실행 후 중단
            final_state = await graph.ainvoke(initial_state, config)
            # 중단 상태인지 확인
            snapshot = await graph.aget_state(config)
            interrupted = bool(snapshot.next)
        else:
            raise HTTPException(status_code=404, detail=f"Unknown workflow: {name}")

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("workflow 실행 실패: %s", name)
        elapsed_ms = int((time.monotonic() - start) * 1000)
        _log_workflow(user, name, params, None, [], elapsed_ms, f"{type(e).__name__}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Workflow 실행 실패: {type(e).__name__}",
        )

    elapsed_ms = int((time.monotonic() - start) * 1000)
    trace = list(final_state.get("trace", []))

    # 로깅 (비차단)
    _log_workflow(user, name, params, dict(final_state), trace, elapsed_ms, None)

    # 응답 shape: 라우터의 WorkflowResponse 와 일치
    # final_state 전체를 result 에 담되, user 같은 민감/불필요 키는 제거
    result_payload = {k: v for k, v in final_state.items() if k not in ("user", "trace")}
    return {
        "result": result_payload,
        "graph_trace": trace,
        "duration_ms": elapsed_ms,
        "thread_id": thread_id,
        "interrupted": interrupted,
    }


async def resume(thread_id: str, user: dict, body: dict[str, Any]) -> dict[str, Any]:
    """interrupt 된 workflow 를 승인/거절로 재개한다.

    Args:
        thread_id: 처음 실행 시 돌려준 thread_id (graph state 키).
        user: get_current_user 결과.
        body: {"approved": bool, "edits": dict | None}
    """
    approved = bool(body.get("approved", False))
    edits = body.get("edits")
    config = {"configurable": {"thread_id": thread_id}}

    # 현재까지는 proactive_risk_alert 만 interrupt 를 사용한다.
    # 다른 workflow 도 interrupt 를 쓰게 되면 여기 분기 추가.
    graph = get_proactive_alert_graph()

    # 현재 state 조회 (권한 검증 및 흐름 확인)
    try:
        snapshot = await graph.aget_state(config)
    except Exception as e:
        raise HTTPException(
            status_code=404,
            detail=f"해당 thread_id 의 workflow 상태를 찾을 수 없습니다: {e}",
        )

    if not snapshot or not snapshot.values:
        raise HTTPException(status_code=404, detail="workflow 상태 없음 또는 만료")

    # state 에 저장된 user 와 현재 호출자가 동일해야 함 (RBAC)
    state_user = snapshot.values.get("user") or {}
    if state_user.get("id") != user.get("id") and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="해당 workflow 의 소유자가 아닙니다.")

    start = time.monotonic()

    if not approved:
        # 거절: 재개하지 않고 로그만 기록
        elapsed_ms = int((time.monotonic() - start) * 1000)
        _log_workflow(
            user,
            "proactive_risk_alert",
            {"approved": False},
            None,
            list(snapshot.values.get("trace", [])),
            elapsed_ms,
            "user_rejected",
        )
        return {
            "result": {
                "approved": False,
                "message": "사용자가 알림 발송을 거절했습니다.",
                "draft_notifications": snapshot.values.get("draft_notifications", []),
            },
            "graph_trace": list(snapshot.values.get("trace", [])),
            "duration_ms": elapsed_ms,
            "thread_id": thread_id,
            "interrupted": False,
        }

    # 승인: 사용자가 초안을 수정했으면 state 업데이트
    if edits and isinstance(edits, dict) and "draft_notifications" in edits:
        try:
            await graph.aupdate_state(
                config,
                {"draft_notifications": edits["draft_notifications"]},
            )
        except Exception as e:
            logger.warning("aupdate_state 실패: %s", e)

    # graph 재개 — input=None 이면 이전 상태에서 계속
    try:
        final_state = await graph.ainvoke(None, config)
    except Exception as e:
        logger.exception("proactive_risk_alert resume 실패")
        elapsed_ms = int((time.monotonic() - start) * 1000)
        _log_workflow(
            user,
            "proactive_risk_alert",
            {"approved": True},
            None,
            list(snapshot.values.get("trace", [])),
            elapsed_ms,
            f"{type(e).__name__}: {e}",
        )
        raise HTTPException(
            status_code=500,
            detail=f"Workflow 재개 실패: {type(e).__name__}",
        )

    elapsed_ms = int((time.monotonic() - start) * 1000)
    trace = list(final_state.get("trace", []))
    _log_workflow(
        user,
        "proactive_risk_alert",
        {"approved": True, "edits": bool(edits)},
        dict(final_state),
        trace,
        elapsed_ms,
        None,
    )

    result_payload = {
        k: v for k, v in final_state.items() if k not in ("user", "trace")
    }
    return {
        "result": result_payload,
        "graph_trace": trace,
        "duration_ms": elapsed_ms,
        "thread_id": thread_id,
        "interrupted": False,
    }
