from datetime import datetime, timezone
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.dependencies import get_current_user, get_teacher_or_admin
from app.utils.supabase_client import get_supabase
from app.schemas.question import QuestionCreateRequest, QuestionResponse

router = APIRouter(prefix="/api/questions", tags=["questions"])


@router.get("", response_model=List[QuestionResponse])
def list_questions(user=Depends(get_current_user)):
    """질문 목록 조회 (익명 포함)"""
    supabase = get_supabase()

    res = (
        supabase.table("questions")
        .select("*, users(name)")
        .order("created_at", desc=True)
        .execute()
    )
    questions = res.data or []

    result = []
    for q in questions:
        user_data = q.get("users") or {}
        # 익명 질문은 작성자 이름 숨김
        # author 컬럼 우선 사용, 없으면 users 조인 결과 사용
        author = None
        if not q.get("is_anonymous"):
            stored_author = q.get("author")
            joined_name = user_data.get("name") if isinstance(user_data, dict) else None
            author = stored_author or joined_name

        result.append(
            QuestionResponse(
                id=str(q["id"]),
                user_id=str(q["user_id"]),
                content=q["content"],
                is_anonymous=q.get("is_anonymous", False),
                author=author,
                created_at=q.get("created_at", ""),
                answer=q.get("answer"),
                answered_at=q.get("answered_at"),
            )
        )
    return result


@router.post("", response_model=QuestionResponse)
def create_question(body: QuestionCreateRequest, user=Depends(get_current_user)):
    """질문 등록"""
    supabase = get_supabase()

    # 작성자 이름 조회 (익명이 아닌 경우, insert 전에 미리 가져옴)
    author = None
    if not body.is_anonymous:
        user_res = (
            supabase.table("users")
            .select("name")
            .eq("id", user["id"])
            .execute()
        )
        author = user_res.data[0].get("name") if user_res.data else None

    res = (
        supabase.table("questions")
        .insert(
            {
                "user_id": user["id"],
                "content": body.content,
                "is_anonymous": body.is_anonymous,
                "author": author,  # DB에 이름 저장
            }
        )
        .execute()
    )
    q = res.data[0]

    return QuestionResponse(
        id=str(q["id"]),
        user_id=str(q["user_id"]),
        content=q["content"],
        is_anonymous=q.get("is_anonymous", False),
        author=author,
        created_at=q.get("created_at", ""),
        answer=None,
        answered_at=None,
    )


class QuestionUpdateRequest(BaseModel):
    content: str


@router.patch("/{question_id}", response_model=QuestionResponse)
def update_question(question_id: str, body: QuestionUpdateRequest, user=Depends(get_current_user)):
    """내 질문 내용 수정 (답변 전에만 가능)"""
    supabase = get_supabase()

    content = body.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="질문 내용을 입력해주세요.")

    res = (
        supabase.table("questions")
        .select("id, user_id, answer")
        .eq("id", question_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="질문을 찾을 수 없습니다.")

    q = res.data[0]
    if q.get("user_id") != user["id"]:
        raise HTTPException(status_code=403, detail="본인의 질문만 수정할 수 있습니다.")
    if q.get("answer"):
        raise HTTPException(status_code=409, detail="답변이 달린 질문은 수정할 수 없습니다.")

    supabase.table("questions").update({"content": content}).eq("id", question_id).execute()

    # update 후 별도 조회 (Supabase Python 클라이언트는 update 체이닝 select 미지원)
    refreshed = (
        supabase.table("questions")
        .select("*, users(name)")
        .eq("id", question_id)
        .execute()
    )
    uq = refreshed.data[0]
    user_data = uq.get("users") or {}
    author = None
    if not uq.get("is_anonymous"):
        author = uq.get("author") or (user_data.get("name") if isinstance(user_data, dict) else None)

    return QuestionResponse(
        id=str(uq["id"]),
        user_id=str(uq["user_id"]),
        content=uq["content"],
        is_anonymous=uq.get("is_anonymous", False),
        author=author,
        created_at=uq.get("created_at", ""),
        answer=uq.get("answer"),
        answered_at=uq.get("answered_at"),
    )


@router.delete("/{question_id}")
def delete_question(question_id: str, user=Depends(get_current_user)):
    """내 질문 삭제"""
    supabase = get_supabase()

    res = (
        supabase.table("questions")
        .select("id, user_id")
        .eq("id", question_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="질문을 찾을 수 없습니다.")
    if res.data[0].get("user_id") != user["id"]:
        raise HTTPException(status_code=403, detail="본인의 질문만 삭제할 수 있습니다.")

    supabase.table("questions").delete().eq("id", question_id).execute()
    return {"message": "질문이 삭제되었습니다."}


class AnswerRequest(BaseModel):
    answer: str


@router.post("/{question_id}/answer")
def answer_question(
    question_id: str,
    body: AnswerRequest,
    user=Depends(get_teacher_or_admin),
):
    """질문에 답변 등록/수정 (강사/관리자 전용)"""
    supabase = get_supabase()

    existing = (
        supabase.table("questions")
        .select("id")
        .eq("id", question_id)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail="질문을 찾을 수 없습니다.")

    supabase.table("questions").update({
        "answer": body.answer,
        "answered_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", question_id).execute()

    return {"message": "답변이 등록되었습니다."}

