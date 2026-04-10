from fastapi import APIRouter, HTTPException, Depends
from app.schemas.interview import (
    InterviewStartRequest,
    InterviewStartResponse,
    InterviewAnswerRequest,
    InterviewAnswerResponse,
    InterviewEndRequest,
    InterviewReport,
    InterviewHistoryItem,
    InterviewHistoryDetail,
)
from app.services import interview_service
from app.dependencies import get_current_user

router = APIRouter(prefix="/api/interview", tags=["interview"])


@router.get("/options")
async def get_options():
    """드롭다운 선택지 반환 (회사, 포지션, 면접 유형)"""
    return interview_service.get_interview_options()


@router.post("/start", response_model=InterviewStartResponse)
async def start_interview(body: InterviewStartRequest, user=Depends(get_current_user)):
    """면접 세션 시작 및 첫 번째 질문 반환"""
    try:
        result = await interview_service.start_interview(
            company=body.company,
            position=body.position,
            interview_type=body.interview_type,
            user_id=user["id"],
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/answer", response_model=InterviewAnswerResponse)
async def submit_answer(body: InterviewAnswerRequest, user=Depends(get_current_user)):
    """답변 제출 후 다음 질문 반환"""
    try:
        result = await interview_service.process_answer(
            session_id=body.session_id,
            answer=body.answer,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/end", response_model=InterviewReport)
async def end_interview(body: InterviewEndRequest, user=Depends(get_current_user)):
    """면접 종료 및 평가 리포트 반환"""
    try:
        report = await interview_service.end_interview(
            session_id=body.session_id,
            user_id=user["id"],
        )
        return report
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history", response_model=list[InterviewHistoryItem])
async def get_interview_history(user=Depends(get_current_user)):
    """AI 모의면접 기록 목록 조회 (최신순)"""
    from app.utils.supabase_client import get_supabase
    supabase = get_supabase()

    res = (
        supabase.table("mock_interviews")
        .select("id, company, position, interview_type, score, report, created_at")
        .eq("user_id", user["id"])
        .order("created_at", desc=True)
        .execute()
    )
    result = []
    for r in (res.data or []):
        report = r.get("report") or {}
        result.append(InterviewHistoryItem(
            id=str(r["id"]),
            company=r.get("company", ""),
            position=r.get("position", ""),
            interview_type=r.get("interview_type", ""),
            score=r.get("score") or 0,
            categories=report.get("categories"),
            created_at=str(r.get("created_at", "")),
        ))
    return result


@router.get("/history/{interview_id}", response_model=InterviewHistoryDetail)
async def get_interview_detail(interview_id: int, user=Depends(get_current_user)):
    """AI 모의면접 상세 기록 조회 (Q&A + 리포트)"""
    from app.utils.supabase_client import get_supabase
    supabase = get_supabase()

    res = (
        supabase.table("mock_interviews")
        .select("*")
        .eq("id", interview_id)
        .eq("user_id", user["id"])
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="면접 기록을 찾을 수 없습니다.")

    r = res.data[0]
    report = r.get("report") or {}
    return InterviewHistoryDetail(
        id=str(r["id"]),
        company=r.get("company", ""),
        position=r.get("position", ""),
        interview_type=r.get("interview_type", ""),
        score=r.get("score") or 0,
        categories=report.get("categories"),
        summary=report.get("summary"),
        improvements=report.get("improvements") or [],
        questions=r.get("questions") or [],
        answers=r.get("answers") or [],
        created_at=str(r.get("created_at", "")),
    )
