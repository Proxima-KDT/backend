from fastapi import APIRouter, HTTPException, Depends
from app.schemas.interview import (
    InterviewStartRequest,
    InterviewStartResponse,
    InterviewAnswerRequest,
    InterviewAnswerResponse,
    InterviewEndRequest,
    InterviewReport,
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
