"""Path A: Direct OpenAI SDK + Function Calling 기반 단일 턴 Q&A.

이 모듈은 다음을 담당한다:
- 역할별 시스템 프롬프트 / Function Calling tool 스키마
- 13개 tool (학생 5 / 강사 4 / 관리자 4) 의 실제 Supabase 쿼리 구현
- OpenAI chat.completions.create + tool_call loop (최대 3 턴)
- RBAC 이중 방어선: 스키마 노출 제한 + dispatch 시 재검증
- agent_logs 테이블 비차단 로깅 (실패해도 응답 반환)
- get_role_summary: 사이드 패널용 AI 호출 없는 고정 쿼리
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from app.services.ai_service import _get_client  # OpenAI 클라이언트 재사용
from app.utils.supabase_client import get_supabase

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

# 파이프라인 제어 상수
MAX_TOOL_LOOPS = 3          # tool call → result → model 재호출 최대 반복
MAX_HISTORY_TURNS = 10      # 세션 내 유지하는 이전 대화 턴 수 (성능/비용)
MODEL_NAME = "gpt-4o-mini"
TEMPERATURE = 0.2
MAX_TOKENS = 800


# ============================================================
# System prompts — role 별 페르소나 / 권한 / 말투 명시
# ============================================================

_SYS_STUDENT = """당신은 EduPilot 의 학생 전용 AI 학습코치입니다.

책임:
- 학생 본인의 출석, 과제, 점수, 일정, 질문 답변 여부만 조회/안내한다.
- 반드시 제공된 tool 을 호출해 실제 DB 데이터를 기반으로 답하고, 추측하지 않는다.
- 여러 정보가 필요하면 tool 을 여러 번 순차 호출해도 된다.

말투/형식:
- 친근하고 격려하는 톤의 한국어.
- 수치는 구체적으로 (예: "출석률 87%, 총 20일 중 18일 출석").
- 불확실하거나 데이터가 없을 때는 "아직 기록이 없어요" 라고 정직하게 말한다.
- 답변은 3~5문장 이내로 간결하게.

하지 말 것:
- 다른 학생의 개인정보를 조회하거나 언급하지 않는다.
- 강사/관리자 전용 tool 을 호출하지 않는다 (권한 오류가 발생한다).
"""

_SYS_TEACHER = """당신은 EduPilot 의 강사 전용 AI 교수 브리핑 어시스턴트입니다.

책임:
- 담당 클래스의 위험 학생, 출석 현황, 과제 제출 통계, 상담 기록을 조회해 브리핑한다.
- tool 을 호출해 실제 데이터를 가져온 뒤, 교수학습 판단에 도움이 되는 인사이트를 덧붙인다.
- 학생 이름을 구체적으로 호명하되, 평가는 사실 기반으로.

말투/형식:
- 전문적이고 간결한 한국어 경어체.
- 필요 시 bullet 로 정리 (최대 5개).
- 수치와 근거를 함께 제시 (예: "출석률 62% (20일 중 12일)").

하지 말 것:
- 학생 전용 / 관리자 전용 tool 을 호출하지 않는다.
- 데이터에 없는 내용을 추측해 말하지 않는다.
"""

_SYS_ADMIN = """당신은 EduPilot 의 관리자 전용 AI 운영 모니터입니다.

책임:
- 코호트 진도, 장비 현황, 강의실 사용률, 시스템 경고를 조회해 운영 상태를 보고한다.
- 관리자의 의사결정에 필요한 수치와 이상 징후를 우선 제시한다.
- 여러 패널을 조합해야 하면 tool 을 순차 호출한다.

말투/형식:
- 격식 있는 한국어 경어체, 리포트 스타일.
- 핵심 수치 → 이상 징후 → 권장 조치 순으로 구조화.
- 표/bullet 를 적극 활용 (최대 6개 bullet).

하지 말 것:
- 학생/강사 전용 tool 을 호출하지 않는다.
- 데이터 없이 "아마" / "대략" 같은 추측 표현을 쓰지 않는다.
"""

SYSTEM_PROMPTS: dict[str, str] = {
    "student": _SYS_STUDENT,
    "teacher": _SYS_TEACHER,
    "admin": _SYS_ADMIN,
}


# ============================================================
# Tool schemas (OpenAI function calling 포맷)
# ============================================================

STUDENT_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_my_attendance",
            "description": (
                "로그인한 학생 본인의 출석 현황을 조회합니다. "
                "최근 N일 동안의 출석률, 출석/지각/결석/조퇴 일수, 최근 결석·지각 날짜를 반환합니다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "조회 기간(일). 기본 30일, 최대 180일.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_my_recent_assignments",
            "description": (
                "로그인한 학생 본인의 최근 과제 제출 상태를 조회합니다. "
                "각 과제의 제목, 마감일, 제출 상태, 점수, 피드백 요약을 반환합니다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "반환할 최대 개수. 기본 5, 최대 20.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_my_scores",
            "description": (
                "로그인한 학생 본인의 능력단위평가 점수 요약을 조회합니다. "
                "평가 제목, 점수, 합격 여부, 평균/최고 점수를 반환합니다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "반환할 최대 평가 개수. 기본 10.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_my_upcoming_events",
            "description": (
                "로그인한 학생 본인의 앞으로 다가오는 일정을 조회합니다. "
                "과제 마감일, 강의실 예약 등 향후 N일 이내의 이벤트를 통합해 반환합니다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "days_ahead": {
                        "type": "integer",
                        "description": "조회할 미래 기간(일). 기본 7일, 최대 30일.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_my_questions_status",
            "description": (
                "로그인한 학생 본인이 게시판에 올린 질문들의 답변 여부를 조회합니다. "
                "질문 내용 요약, 답변 여부, 답변 일시를 반환합니다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "반환할 최대 질문 개수. 기본 5.",
                    }
                },
                "required": [],
            },
        },
    },
]


TEACHER_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_at_risk_students",
            "description": (
                "위험군 학생을 조회합니다. 출석률이 낮거나, 과제 미제출이 많거나, "
                "평가 점수가 낮은 학생을 식별해 위험 사유와 함께 반환합니다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "threshold_pct": {
                        "type": "integer",
                        "description": "출석률 임계값(%). 이 값 미만을 위험군으로 분류. 기본 80.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "반환 최대 학생 수. 기본 10.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_class_attendance_summary",
            "description": (
                "담당 클래스 전체의 출석 요약을 조회합니다. "
                "오늘 또는 이번 주의 출석/지각/결석 수를 학생별로 반환합니다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "period": {
                        "type": "string",
                        "enum": ["today", "week"],
                        "description": "집계 기간. today=오늘 하루, week=최근 7일.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_assignment_submission_stats",
            "description": (
                "과제 제출 통계를 조회합니다. "
                "특정 과제 또는 최근 과제 전체에 대해 제출률, 평균 점수, 미제출 학생 수를 반환합니다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "assignment_id": {
                        "type": "integer",
                        "description": "특정 과제 ID. 미지정 시 최근 과제 5개를 요약.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_counseling_records",
            "description": (
                "로그인한 강사가 진행한 최근 상담 기록을 조회합니다. "
                "상담 일자, 학생 이름, 요약, 액션 아이템을 반환합니다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "반환 최대 개수. 기본 10.",
                    }
                },
                "required": [],
            },
        },
    },
]


ADMIN_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_cohort_progress",
            "description": (
                "진행 중인 코호트들의 커리큘럼 진도 현황을 조회합니다. "
                "코호트별 현재 phase, progress%, 학생 수, 시작/종료일을 반환합니다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "cohort_id": {
                        "type": "integer",
                        "description": "특정 코호트 ID. 미지정 시 전체 in_progress 코호트.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_equipment_status",
            "description": (
                "장비 재고 및 상태를 조회합니다. "
                "카테고리별 가용/사용중/수리중 수량과 대여 중인 장비의 대여자·기간을 반환합니다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "장비 카테고리 필터 (예: 'laptop'). 미지정 시 전체.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_room_utilization",
            "description": (
                "강의실 사용률을 조회합니다. "
                "특정 날짜의 강의실별 예약 건수와 점유율을 반환합니다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target_date": {
                        "type": "string",
                        "description": "조회 날짜 (YYYY-MM-DD). 미지정 시 오늘.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_global_alerts",
            "description": (
                "시스템 전체의 agent_notifications 테이블에서 최근 경고를 조회합니다. "
                "severity (high/medium/low) 로 필터링 가능."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "severity": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                        "description": "심각도 필터. 미지정 시 전체.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "반환 최대 개수. 기본 10.",
                    },
                },
                "required": [],
            },
        },
    },
]


# role 별 tool 스키마 (RBAC 1차 방어선: 스키마 노출 제한)
_TOOLS_BY_ROLE: dict[str, list[dict]] = {
    "student": STUDENT_TOOLS,
    "teacher": TEACHER_TOOLS,
    "admin": ADMIN_TOOLS,
}

# tool 이름 → 필요 role (RBAC 2차 방어선: dispatch 시 재검증)
_TOOL_REQUIRED_ROLE: dict[str, str] = {
    **{t["function"]["name"]: "student" for t in STUDENT_TOOLS},
    **{t["function"]["name"]: "teacher" for t in TEACHER_TOOLS},
    **{t["function"]["name"]: "admin" for t in ADMIN_TOOLS},
}


def _get_tool_schemas(role: str) -> list[dict]:
    """role 에 허용된 tool 스키마만 반환."""
    return _TOOLS_BY_ROLE.get(role, [])


# ============================================================
# Tool 구현 — Student (5개)
#
# 모든 학생 tool 은 user["id"] 를 서버에서 강제 주입한다.
# arguments 에 user_id 가 들어와도 무시한다.
# ============================================================


def _tool_get_my_attendance(args: dict, user: dict) -> dict:
    days = max(1, min(int(args.get("days", 30) or 30), 180))
    supabase = get_supabase()
    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    res = (
        supabase.table("attendance")
        .select("date, status, check_in_time, check_out_time")
        .eq("user_id", user["id"])
        .gte("date", start_date.isoformat())
        .lte("date", end_date.isoformat())
        .order("date", desc=True)
        .execute()
    )
    records = res.data or []
    total = len(records)
    counts = {"present": 0, "late": 0, "absent": 0, "early_leave": 0, "checked_in": 0}
    for r in records:
        s = r.get("status")
        if s in counts:
            counts[s] += 1
    attended = counts["present"] + counts["late"]
    rate = round((attended / total) * 100, 1) if total > 0 else 0.0

    return {
        "period_days": days,
        "period_start": start_date.isoformat(),
        "period_end": end_date.isoformat(),
        "total_records": total,
        "present": counts["present"],
        "late": counts["late"],
        "absent": counts["absent"],
        "early_leave": counts["early_leave"],
        "attendance_rate_pct": rate,
        "recent_absences_and_late": [
            {"date": r["date"], "status": r["status"]}
            for r in records
            if r.get("status") in ("absent", "late", "early_leave")
        ][:5],
    }


def _tool_get_my_recent_assignments(args: dict, user: dict) -> dict:
    limit = max(1, min(int(args.get("limit", 5) or 5), 20))
    supabase = get_supabase()

    # 본인 제출 기록 (없는 과제는 미제출로 표시되어야 하므로 분리 조회)
    subs_res = (
        supabase.table("assignment_submissions")
        .select("id, assignment_id, status, score, submitted_at, feedback")
        .eq("student_id", user["id"])
        .order("submitted_at", desc=True)
        .limit(limit)
        .execute()
    )
    subs = subs_res.data or []

    # 각 과제 상세 병합
    assignment_ids = [s["assignment_id"] for s in subs if s.get("assignment_id")]
    assignments_map: dict[int, dict] = {}
    if assignment_ids:
        ar = (
            supabase.table("assignments")
            .select("id, title, subject, due_date, max_score")
            .in_("id", assignment_ids)
            .execute()
        )
        assignments_map = {a["id"]: a for a in (ar.data or [])}

    items = []
    for s in subs:
        a = assignments_map.get(s.get("assignment_id"), {})
        items.append(
            {
                "assignment_id": s.get("assignment_id"),
                "title": a.get("title"),
                "subject": a.get("subject"),
                "due_date": a.get("due_date"),
                "max_score": a.get("max_score"),
                "status": s.get("status"),
                "score": s.get("score"),
                "submitted_at": s.get("submitted_at"),
                "feedback_preview": (s.get("feedback") or "")[:200],
            }
        )
    return {"count": len(items), "items": items}


def _tool_get_my_scores(args: dict, user: dict) -> dict:
    limit = max(1, min(int(args.get("limit", 10) or 10), 30))
    supabase = get_supabase()

    res = (
        supabase.table("assessment_submissions")
        .select("id, assessment_id, score, passed, status, submitted_at, feedback")
        .eq("student_id", user["id"])
        .order("submitted_at", desc=True)
        .limit(limit)
        .execute()
    )
    subs = res.data or []

    assessment_ids = [s["assessment_id"] for s in subs if s.get("assessment_id")]
    assessment_map: dict[int, dict] = {}
    if assessment_ids:
        ar = (
            supabase.table("assessments")
            .select("id, title, max_score")
            .in_("id", assessment_ids)
            .execute()
        )
        assessment_map = {a["id"]: a for a in (ar.data or [])}

    scored = [s for s in subs if s.get("score") is not None]
    avg = round(sum(s["score"] for s in scored) / len(scored), 1) if scored else None
    highest = max((s["score"] for s in scored), default=None)

    items = []
    for s in subs:
        a = assessment_map.get(s.get("assessment_id"), {})
        items.append(
            {
                "assessment_id": s.get("assessment_id"),
                "title": a.get("title"),
                "max_score": a.get("max_score"),
                "score": s.get("score"),
                "passed": s.get("passed"),
                "status": s.get("status"),
                "submitted_at": s.get("submitted_at"),
            }
        )
    return {
        "count": len(items),
        "average_score": avg,
        "highest_score": highest,
        "items": items,
    }


def _tool_get_my_upcoming_events(args: dict, user: dict) -> dict:
    days_ahead = max(1, min(int(args.get("days_ahead", 7) or 7), 30))
    supabase = get_supabase()
    today = date.today()
    end = today + timedelta(days=days_ahead)

    # 1) 다가오는 과제 마감 (본인이 미제출이거나 상관없이 마감일 기준)
    ar = (
        supabase.table("assignments")
        .select("id, title, subject, due_date")
        .gte("due_date", today.isoformat())
        .lte("due_date", end.isoformat())
        .order("due_date")
        .execute()
    )
    upcoming_assignments = ar.data or []

    # 2) 본인 강의실 예약
    rr = (
        supabase.table("room_reservations")
        .select("id, room_name, date, start_time, end_time, purpose, status")
        .eq("user_id", user["id"])
        .gte("date", today.isoformat())
        .lte("date", end.isoformat())
        .order("date")
        .execute()
    )
    upcoming_rooms = rr.data or []

    events: list[dict] = []
    for a in upcoming_assignments:
        events.append(
            {
                "type": "assignment_due",
                "date": a.get("due_date"),
                "title": a.get("title"),
                "subject": a.get("subject"),
            }
        )
    for r in upcoming_rooms:
        events.append(
            {
                "type": "room_reservation",
                "date": r.get("date"),
                "room": r.get("room_name"),
                "time": f"{r.get('start_time')}~{r.get('end_time')}",
                "purpose": r.get("purpose"),
                "status": r.get("status"),
            }
        )
    events.sort(key=lambda e: e.get("date") or "9999-12-31")
    return {"days_ahead": days_ahead, "count": len(events), "events": events[:20]}


def _tool_get_my_questions_status(args: dict, user: dict) -> dict:
    limit = max(1, min(int(args.get("limit", 5) or 5), 20))
    supabase = get_supabase()

    res = (
        supabase.table("questions")
        .select("id, content, answer, answered_at, created_at")
        .eq("user_id", user["id"])
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    items = []
    for q in res.data or []:
        items.append(
            {
                "id": q.get("id"),
                "content_preview": (q.get("content") or "")[:150],
                "is_answered": bool(q.get("answer")),
                "answered_at": q.get("answered_at"),
                "created_at": q.get("created_at"),
            }
        )
    answered_count = sum(1 for i in items if i["is_answered"])
    return {
        "total": len(items),
        "answered": answered_count,
        "pending": len(items) - answered_count,
        "items": items,
    }


# ============================================================
# Tool 구현 — Teacher (4개)
# ============================================================


def _get_teacher_student_ids(
    supabase,
    teacher_id: str,
    filter_course_id: str | None = None,
) -> list[str]:
    """teacher_courses → users 순으로 조회해 강사 담당 학생 ID 목록 반환.

    filter_course_id 가 주어지면 해당 과정 학생만 반환한다.
    강사가 담당하지 않는 course_id 를 지정하면 빈 목록(보안 차단) 반환.
    """
    try:
        tc = (
            supabase.table("teacher_courses")
            .select("course_id")
            .eq("teacher_id", teacher_id)
            .execute()
        )
        all_course_ids = [r["course_id"] for r in (tc.data or [])]
        if not all_course_ids:
            return []

        if filter_course_id:
            # 강사가 담당하지 않는 course 는 차단
            course_ids = [filter_course_id] if filter_course_id in all_course_ids else []
        else:
            course_ids = all_course_ids

        if not course_ids:
            return []

        ur = (
            supabase.table("users")
            .select("id")
            .in_("course_id", course_ids)
            .eq("role", "student")
            .execute()
        )
        return [u["id"] for u in (ur.data or [])]
    except Exception as e:
        logger.warning("_get_teacher_student_ids 실패: %s", e)
        return []


def _tool_get_at_risk_students(args: dict, user: dict) -> dict:
    threshold_pct = max(0, min(int(args.get("threshold_pct", 80) or 80), 100))
    limit = max(1, min(int(args.get("limit", 10) or 10), 30))
    supabase = get_supabase()

    # 담당 과정 학생만 대상으로 한정 (course_id 지정 시 단일 과정)
    filter_course_id = args.get("course_id") or None
    teacher_student_ids = _get_teacher_student_ids(supabase, user["id"], filter_course_id)
    if not teacher_student_ids:
        return {"threshold_pct": threshold_pct, "count": 0, "students": []}

    # 최근 30일 출석 기록 — 담당 학생만 조회
    since = (date.today() - timedelta(days=30)).isoformat()
    att_res = (
        supabase.table("attendance")
        .select("user_id, status")
        .gte("date", since)
        .in_("user_id", teacher_student_ids)
        .execute()
    )
    rows = att_res.data or []

    per_student: dict[str, dict] = {}
    for r in rows:
        uid = r.get("user_id")
        if not uid:
            continue
        agg = per_student.setdefault(uid, {"total": 0, "attended": 0, "absent": 0})
        agg["total"] += 1
        if r.get("status") in ("present", "late"):
            agg["attended"] += 1
        elif r.get("status") == "absent":
            agg["absent"] += 1

    # 위험군 필터링: 출석률 threshold 미만
    at_risk_ids: list[tuple[str, float, int]] = []
    for uid, agg in per_student.items():
        total = agg["total"]
        if total < 5:
            continue  # 표본이 너무 적으면 제외
        rate = round((agg["attended"] / total) * 100, 1)
        if rate < threshold_pct:
            at_risk_ids.append((uid, rate, agg["absent"]))

    at_risk_ids.sort(key=lambda x: x[1])  # 낮은 순
    at_risk_ids = at_risk_ids[:limit]

    # 학생 이름 조회
    ids_only = [x[0] for x in at_risk_ids]
    name_map: dict[str, str] = {}
    if ids_only:
        ur = (
            supabase.table("users")
            .select("id, name, email, cohort_id")
            .in_("id", ids_only)
            .eq("role", "student")
            .execute()
        )
        for u in ur.data or []:
            name_map[u["id"]] = u.get("name") or u.get("email") or "이름없음"

    items = [
        {
            "student_id": uid,
            "name": name_map.get(uid, "알 수 없음"),
            "attendance_rate_pct": rate,
            "absent_count_30d": absent,
            "reason": f"최근 30일 출석률 {rate}% (임계 {threshold_pct}%)",
        }
        for uid, rate, absent in at_risk_ids
    ]
    return {
        "threshold_pct": threshold_pct,
        "count": len(items),
        "students": items,
    }


def _tool_get_class_attendance_summary(args: dict, user: dict) -> dict:
    period = args.get("period") or "today"
    supabase = get_supabase()
    today = date.today()

    if period == "week":
        start = today - timedelta(days=6)
    else:
        start = today

    # 담당 과정 학생만 대상으로 한정 (course_id 지정 시 단일 과정)
    filter_course_id = args.get("course_id") or None
    teacher_student_ids = _get_teacher_student_ids(supabase, user["id"], filter_course_id)
    if not teacher_student_ids:
        return {
            "period": period,
            "period_start": start.isoformat(),
            "period_end": today.isoformat(),
            "unique_students": 0,
            "present": 0,
            "late": 0,
            "absent": 0,
            "early_leave": 0,
            "attendance_rate_pct": 0.0,
            "absent_student_names": [],
        }
    att_res = (
        supabase.table("attendance")
        .select("user_id, date, status")
        .gte("date", start.isoformat())
        .lte("date", today.isoformat())
        .in_("user_id", teacher_student_ids)
        .execute()
    )
    rows = att_res.data or []

    counts = {"present": 0, "late": 0, "absent": 0, "early_leave": 0}
    unique_students: set[str] = set()
    for r in rows:
        s = r.get("status")
        if s in counts:
            counts[s] += 1
        if r.get("user_id"):
            unique_students.add(r["user_id"])

    total = sum(counts.values())
    attended = counts["present"] + counts["late"]
    rate = round((attended / total) * 100, 1) if total > 0 else 0.0

    # 결석 학생 이름 (최대 10명)
    absent_ids = list({r["user_id"] for r in rows if r.get("status") == "absent"})[:10]
    absent_names: list[str] = []
    if absent_ids:
        ur = (
            supabase.table("users")
            .select("id, name")
            .in_("id", absent_ids)
            .execute()
        )
        absent_names = [u.get("name", "알수없음") for u in (ur.data or [])]

    return {
        "period": period,
        "period_start": start.isoformat(),
        "period_end": today.isoformat(),
        "unique_students": len(unique_students),
        "present": counts["present"],
        "late": counts["late"],
        "absent": counts["absent"],
        "early_leave": counts["early_leave"],
        "attendance_rate_pct": rate,
        "absent_student_names": absent_names,
    }


def _tool_get_assignment_submission_stats(args: dict, user: dict) -> dict:
    supabase = get_supabase()
    assignment_id = args.get("assignment_id")

    if assignment_id:
        ar = (
            supabase.table("assignments")
            .select("id, title, due_date, max_score")
            .eq("id", int(assignment_id))
            .execute()
        )
        target_assignments = ar.data or []
    else:
        ar = (
            supabase.table("assignments")
            .select("id, title, due_date, max_score")
            .order("due_date", desc=True)
            .limit(5)
            .execute()
        )
        target_assignments = ar.data or []

    items = []
    for a in target_assignments:
        sr = (
            supabase.table("assignment_submissions")
            .select("id, status, score")
            .eq("assignment_id", a["id"])
            .execute()
        )
        subs = sr.data or []
        submitted = sum(1 for s in subs if s.get("status") in ("submitted", "graded"))
        graded_scores = [s["score"] for s in subs if s.get("score") is not None]
        avg = round(sum(graded_scores) / len(graded_scores), 1) if graded_scores else None
        items.append(
            {
                "assignment_id": a["id"],
                "title": a.get("title"),
                "due_date": a.get("due_date"),
                "max_score": a.get("max_score"),
                "submission_count": submitted,
                "total_records": len(subs),
                "average_score": avg,
            }
        )
    return {"count": len(items), "assignments": items}


def _tool_get_recent_counseling_records(args: dict, user: dict) -> dict:
    limit = max(1, min(int(args.get("limit", 10) or 10), 30))
    supabase = get_supabase()

    res = (
        supabase.table("counseling_records")
        .select("id, student_id, student_name, date, summary, action_items, duration")
        .eq("counselor_id", user["id"])
        .order("date", desc=True)
        .limit(limit)
        .execute()
    )
    items = []
    for r in res.data or []:
        items.append(
            {
                "id": r.get("id"),
                "student_name": r.get("student_name"),
                "date": r.get("date"),
                "duration": r.get("duration"),
                "summary_preview": (r.get("summary") or "")[:200],
                "action_items": r.get("action_items") or [],
            }
        )
    return {"count": len(items), "records": items}


# ============================================================
# Tool 구현 — Admin (4개)
# ============================================================


def _tool_get_cohort_progress(args: dict, user: dict) -> dict:
    supabase = get_supabase()
    cohort_id = args.get("cohort_id")

    if cohort_id:
        cr = (
            supabase.table("cohorts")
            .select("id, course_id, cohort_number, status, start_date, end_date")
            .eq("id", int(cohort_id))
            .execute()
        )
    else:
        cr = (
            supabase.table("cohorts")
            .select("id, course_id, cohort_number, status, start_date, end_date")
            .eq("status", "in_progress")
            .order("start_date", desc=True)
            .execute()
        )
    cohorts = cr.data or []

    # 커리큘럼 진도 평균 (전체 phase 기준)
    cur_res = (
        supabase.table("curriculum")
        .select("phase, progress, status, title")
        .order("phase")
        .execute()
    )
    curriculum_rows = cur_res.data or []
    overall_progress = None
    if curriculum_rows:
        progresses = [
            c.get("progress", 0) or 0 for c in curriculum_rows if c.get("progress") is not None
        ]
        if progresses:
            overall_progress = round(sum(progresses) / len(progresses), 1)

    items = []
    for c in cohorts:
        # 학생 수 집계
        ur = (
            supabase.table("users")
            .select("id", count="exact")
            .eq("cohort_id", c["id"])
            .eq("role", "student")
            .execute()
        )
        student_count = getattr(ur, "count", None)
        if student_count is None:
            student_count = len(ur.data or [])

        items.append(
            {
                "cohort_id": c["id"],
                "course_id": c.get("course_id"),
                "cohort_number": c.get("cohort_number"),
                "status": c.get("status"),
                "start_date": c.get("start_date"),
                "end_date": c.get("end_date"),
                "student_count": student_count,
                "overall_curriculum_progress_pct": overall_progress,
            }
        )
    return {"count": len(items), "cohorts": items}


def _tool_get_equipment_status(args: dict, user: dict) -> dict:
    supabase = get_supabase()
    category = args.get("category")

    q = supabase.table("equipment").select(
        "id, name, serial_no, category, status, borrower_name, borrowed_at"
    )
    if category:
        q = q.eq("category", str(category))
    res = q.execute()
    rows = res.data or []

    # 상태별 집계
    status_counts: dict[str, int] = {}
    for r in rows:
        s = r.get("status") or "unknown"
        status_counts[s] = status_counts.get(s, 0) + 1

    # 카테고리별 집계
    category_counts: dict[str, int] = {}
    for r in rows:
        c = r.get("category") or "unknown"
        category_counts[c] = category_counts.get(c, 0) + 1

    in_use = [
        {
            "name": r.get("name"),
            "serial_no": r.get("serial_no"),
            "borrower": r.get("borrower_name"),
            "borrowed_at": r.get("borrowed_at"),
        }
        for r in rows
        if r.get("status") == "in_use"
    ][:10]

    return {
        "total": len(rows),
        "by_status": status_counts,
        "by_category": category_counts,
        "currently_in_use": in_use,
    }


def _tool_get_room_utilization(args: dict, user: dict) -> dict:
    supabase = get_supabase()
    target = args.get("target_date") or date.today().isoformat()

    res = (
        supabase.table("room_reservations")
        .select("room_id, room_name, start_time, end_time, status")
        .eq("date", target)
        .execute()
    )
    rows = res.data or []

    per_room: dict[str, dict] = {}
    for r in rows:
        key = r.get("room_name") or r.get("room_id") or "unknown"
        agg = per_room.setdefault(key, {"count": 0, "confirmed": 0, "pending": 0})
        agg["count"] += 1
        if r.get("status") == "confirmed":
            agg["confirmed"] += 1
        elif r.get("status") == "pending":
            agg["pending"] += 1

    # 전체 강의실 수
    rr = supabase.table("rooms").select("id, name, type, capacity").execute()
    all_rooms = rr.data or []

    return {
        "date": target,
        "total_reservations": len(rows),
        "total_rooms": len(all_rooms),
        "by_room": [{"room": k, **v} for k, v in per_room.items()],
    }


def _tool_get_global_alerts(args: dict, user: dict) -> dict:
    supabase = get_supabase()
    severity = args.get("severity")
    limit = max(1, min(int(args.get("limit", 10) or 10), 30))

    q = (
        supabase.table("agent_notifications")
        .select("id, agent_type, severity, title, message, created_at, read_at")
        .order("created_at", desc=True)
        .limit(limit)
    )
    if severity:
        q = q.eq("severity", str(severity))
    try:
        res = q.execute()
        rows = res.data or []
    except Exception as e:
        logger.warning("agent_notifications 조회 실패: %s", e)
        rows = []

    return {
        "severity_filter": severity,
        "count": len(rows),
        "alerts": [
            {
                "id": r.get("id"),
                "agent_type": r.get("agent_type"),
                "severity": r.get("severity"),
                "title": r.get("title"),
                "message_preview": (r.get("message") or "")[:200],
                "created_at": r.get("created_at"),
                "is_read": r.get("read_at") is not None,
            }
            for r in rows
        ],
    }


# ============================================================
# Tool dispatcher — RBAC 2차 방어선 + 에러 표준화
# ============================================================

_TOOL_IMPL: dict[str, Callable[[dict, dict], dict]] = {
    "get_my_attendance": _tool_get_my_attendance,
    "get_my_recent_assignments": _tool_get_my_recent_assignments,
    "get_my_scores": _tool_get_my_scores,
    "get_my_upcoming_events": _tool_get_my_upcoming_events,
    "get_my_questions_status": _tool_get_my_questions_status,
    "get_at_risk_students": _tool_get_at_risk_students,
    "get_class_attendance_summary": _tool_get_class_attendance_summary,
    "get_assignment_submission_stats": _tool_get_assignment_submission_stats,
    "get_recent_counseling_records": _tool_get_recent_counseling_records,
    "get_cohort_progress": _tool_get_cohort_progress,
    "get_equipment_status": _tool_get_equipment_status,
    "get_room_utilization": _tool_get_room_utilization,
    "get_global_alerts": _tool_get_global_alerts,
}


def _dispatch_tool(name: str, args: dict, user: dict) -> dict:
    """tool 이름 → 실제 구현 호출. RBAC 검증 + 예외 표준화."""
    required_role = _TOOL_REQUIRED_ROLE.get(name)
    if required_role is None:
        return {"error": f"Unknown tool: {name}"}
    if user.get("role") != required_role:
        return {
            "error": (
                f"권한 없음: '{name}' 은 {required_role} 전용이지만 "
                f"사용자 role='{user.get('role')}' 입니다."
            )
        }
    impl = _TOOL_IMPL.get(name)
    if impl is None:
        return {"error": f"Tool 구현 없음: {name}"}
    try:
        return impl(args or {}, user)
    except Exception as e:
        logger.exception("Tool %s 실행 실패", name)
        return {"error": f"{name} 실행 중 오류: {type(e).__name__}: {e}"}


# ============================================================
# 메인 파이프라인: run_direct
# ============================================================


async def run_direct(
    user: dict,
    message: str,
    history: list[dict] | None = None,
) -> dict[str, Any]:
    """단일 턴 Function Calling 파이프라인.

    Args:
        user: get_current_user 가 돌려준 {id, role, email} dict.
        message: 사용자의 한 줄 입력.
        history: 세션 내 이전 대화 [{role, content}, ...] (최대 MAX_HISTORY_TURNS).

    Returns:
        AgentChatResponse shape 의 dict.
    """
    role = user.get("role") or "student"
    system_prompt = SYSTEM_PROMPTS.get(role, SYSTEM_PROMPTS["student"])
    tools = _get_tool_schemas(role)

    # 메시지 조합 (history 는 최근 N 턴으로 제한)
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    if history:
        trimmed = history[-MAX_HISTORY_TURNS:]
        for m in trimmed:
            if isinstance(m, dict) and m.get("role") in ("user", "assistant"):
                messages.append({"role": m["role"], "content": m.get("content", "")})
    messages.append({"role": "user", "content": message})

    client = _get_client()
    tool_records: list[dict] = []
    final_answer: str = ""
    start = time.monotonic()

    try:
        for _loop in range(MAX_TOOL_LOOPS):
            response = await client.chat.completions.create(
                model=MODEL_NAME,
                messages=messages,
                tools=tools if tools else None,
                tool_choice="auto" if tools else None,
                temperature=TEMPERATURE,
                max_tokens=MAX_TOKENS,
            )
            msg = response.choices[0].message

            if not msg.tool_calls:
                final_answer = msg.content or ""
                break

            # assistant 가 호출한 tool 을 다시 messages 에 포함시켜 재호출 준비
            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in msg.tool_calls
                    ],
                }
            )

            for tc in msg.tool_calls:
                tool_name = tc.function.name
                try:
                    tool_args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    tool_args = {}
                tool_result = _dispatch_tool(tool_name, tool_args, user)

                # OpenAI tool 결과 메시지
                tool_content = json.dumps(tool_result, ensure_ascii=False, default=str)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_content[:6000],  # 과도한 길이 방지
                    }
                )
                tool_records.append(
                    {
                        "name": tool_name,
                        "args": tool_args,
                        "result_preview": tool_content[:500],
                    }
                )
        else:
            # MAX_TOOL_LOOPS 소진 — 마지막 한 번 더 호출해 최종 답 확보
            response = await client.chat.completions.create(
                model=MODEL_NAME,
                messages=messages,
                temperature=TEMPERATURE,
                max_tokens=MAX_TOKENS,
            )
            final_answer = response.choices[0].message.content or ""
    except Exception as e:
        logger.exception("run_direct 실패")
        elapsed_ms = int((time.monotonic() - start) * 1000)
        _log_to_supabase(
            user, "chat", message, None, tool_records, elapsed_ms, f"{type(e).__name__}: {e}"
        )
        return {
            "answer": "AI 응답 중 오류가 발생했어요. 잠시 후 다시 시도해주세요.",
            "tool_calls": [],
            "duration_ms": elapsed_ms,
            "path": "direct",
        }

    if not final_answer:
        final_answer = "죄송해요, 답변을 생성하지 못했어요. 질문을 조금 바꿔서 다시 해주세요."

    elapsed_ms = int((time.monotonic() - start) * 1000)
    _log_to_supabase(user, "chat", message, final_answer, tool_records, elapsed_ms, None)

    return {
        "answer": final_answer,
        "tool_calls": tool_records,
        "duration_ms": elapsed_ms,
        "path": "direct",
    }


# ============================================================
# 로깅 — agent_logs 테이블 insert (비차단)
# ============================================================


def _log_to_supabase(
    user: dict,
    trigger: str,
    input_message: str,
    output_answer: str | None,
    tool_records: list[dict],
    duration_ms: int,
    error: str | None,
) -> None:
    """agent_logs insert. 실패해도 예외를 삼킨다 (응답 차단 방지)."""
    try:
        supabase = get_supabase()
        supabase.table("agent_logs").insert(
            {
                "agent_type": user.get("role") or "unknown",
                "trigger": trigger,
                "user_id": user.get("id"),
                "input": {
                    "message": input_message[:2000],
                    "role": user.get("role"),
                },
                "output": (
                    {"answer": (output_answer or "")[:3000]}
                    if output_answer is not None
                    else None
                ),
                "tool_calls": tool_records,
                "duration_ms": duration_ms,
                "error": error,
            }
        ).execute()
    except Exception as e:
        logger.warning("agent_logs insert 실패 (무시하고 응답 반환): %s", e)


# ============================================================
# 대화 이력 조회 — agent_logs 에서 최근 N건 chat 로그 반환
# ============================================================


async def get_chat_history(user: dict, limit: int = 20) -> list[dict]:
    """agent_logs 에서 유저의 최근 채팅 이력을 메시지 배열로 반환.

    trigger = 'chat' 인 로그만 조회하고, 오래된 순으로 정렬해 반환한다.
    각 로그 1건은 user 메시지 + assistant 메시지 쌍으로 변환된다.
    """
    try:
        supabase = get_supabase()
        resp = (
            supabase.table("agent_logs")
            .select("input, output, tool_calls, duration_ms")
            .eq("user_id", user["id"])
            .eq("trigger", "chat")
            .order("id", desc=True)
            .limit(limit)
            .execute()
        )
        rows = list(reversed(resp.data or []))
    except Exception as e:
        logger.warning("get_chat_history 조회 실패 (빈 배열 반환): %s", e)
        return []

    messages: list[dict] = []
    for row in rows:
        inp = row.get("input") or {}
        out = row.get("output") or {}
        tool_calls = row.get("tool_calls") or []
        duration_ms = row.get("duration_ms")

        user_text = inp.get("message", "")
        assistant_text = out.get("answer", "")

        if user_text:
            messages.append({"role": "user", "content": user_text})
        if assistant_text:
            messages.append(
                {
                    "role": "assistant",
                    "content": assistant_text,
                    "tool_calls": tool_calls,
                    "duration_ms": duration_ms,
                }
            )

    return messages


# ============================================================
# 사이드 패널 요약 — AI 호출 없이 고정 쿼리
# ============================================================


def _summary_student(user: dict) -> list[dict]:
    try:
        att = _tool_get_my_attendance({"days": 30}, user)
        rate = att.get("attendance_rate_pct", 0.0)
        color = "emerald" if rate >= 90 else ("amber" if rate >= 80 else "rose")
    except Exception:
        rate, color = 0.0, "slate"
    try:
        asg = _tool_get_my_recent_assignments({"limit": 5}, user)
        asg_count = asg.get("count", 0)
    except Exception:
        asg_count = 0
    try:
        up = _tool_get_my_upcoming_events({"days_ahead": 7}, user)
        up_count = up.get("count", 0)
    except Exception:
        up_count = 0

    return [
        {
            "title": "내 출석률",
            "value": f"{rate}%",
            "sub": "최근 30일",
            "icon": "CalendarCheck",
            "color": color,
        },
        {
            "title": "최근 과제",
            "value": f"{asg_count}건",
            "sub": "최근 제출 이력",
            "icon": "FileText",
            "color": "blue",
        },
        {
            "title": "다가오는 일정",
            "value": f"{up_count}건",
            "sub": "앞으로 7일",
            "icon": "Bell",
            "color": "violet",
        },
    ]


def _summary_teacher(user: dict) -> list[dict]:
    try:
        today = _tool_get_class_attendance_summary({"period": "today"}, user)
    except Exception:
        today = {"absent": 0, "late": 0, "present": 0}
    try:
        risk = _tool_get_at_risk_students({"threshold_pct": 80, "limit": 10}, user)
        risk_count = risk.get("count", 0)
    except Exception:
        risk_count = 0

    return [
        {
            "title": "오늘 결석",
            "value": f"{today.get('absent', 0)}명",
            "sub": f"지각 {today.get('late', 0)}명 · 조퇴 {today.get('early_leave', 0)}명",
            "icon": "UserX",
            "color": "rose" if today.get("absent", 0) > 0 else "emerald",
        },
        {
            "title": "위험군 학생",
            "value": f"{risk_count}명",
            "sub": "출석률 80% 미만",
            "icon": "AlertTriangle",
            "color": "amber" if risk_count > 0 else "emerald",
        },
        {
            "title": "오늘 출석률",
            "value": f"{today.get('attendance_rate_pct', 0)}%",
            "sub": f"{today.get('unique_students', 0)}명 참여",
            "icon": "TrendingUp",
            "color": "blue",
        },
    ]


def _summary_admin(user: dict) -> list[dict]:
    try:
        coh = _tool_get_cohort_progress({}, user)
        coh_count = coh.get("count", 0)
    except Exception:
        coh_count = 0
    try:
        eq = _tool_get_equipment_status({}, user)
        eq_total = eq.get("total", 0)
        eq_in_use = eq.get("by_status", {}).get("in_use", 0)
        eq_available = eq_total - eq_in_use
    except Exception:
        eq_total, eq_available = 0, 0
    try:
        room = _tool_get_room_utilization({}, user)
        room_reservations = room.get("total_reservations", 0)
    except Exception:
        room_reservations = 0

    return [
        {
            "title": "진행 코호트",
            "value": f"{coh_count}개",
            "sub": "status=in_progress",
            "icon": "Users",
            "color": "blue",
        },
        {
            "title": "가용 장비",
            "value": f"{eq_available}/{eq_total}대",
            "sub": "전체 대비 가용",
            "icon": "Laptop",
            "color": "emerald",
        },
        {
            "title": "오늘 강의실 예약",
            "value": f"{room_reservations}건",
            "sub": date.today().isoformat(),
            "icon": "DoorOpen",
            "color": "violet",
        },
    ]


async def get_role_summary(user: dict) -> dict[str, Any]:
    """사이드 패널 초기 로드용 요약 카드. AI 호출 없이 tool 을 직접 호출."""
    role = user.get("role") or "student"
    try:
        if role == "teacher":
            cards = _summary_teacher(user)
        elif role == "admin":
            cards = _summary_admin(user)
        else:
            cards = _summary_student(user)
    except Exception as e:
        logger.exception("get_role_summary 실패")
        cards = [
            {"title": "요약 로드 실패", "value": "--", "sub": str(e)[:100], "color": "slate"}
        ]
    return {"role": role, "cards": cards}
