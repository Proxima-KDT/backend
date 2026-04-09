from typing import List
from fastapi import APIRouter, Depends, HTTPException
from app.dependencies import get_current_user
from app.utils.supabase_client import get_supabase
from app.schemas.question import QuestionCreateRequest, QuestionResponse

router = APIRouter(prefix="/api/questions", tags=["questions"])


@router.get("", response_model=List[QuestionResponse])
def list_questions(user=Depends(get_current_user)):
    """질문 목록 조회 (익명 포함)"""
    supabase = get_supabase()

    res = (
        supabase.table("questions")
        .select("*, profiles(name)")
        .order("created_at", desc=True)
        .execute()
    )
    questions = res.data or []

    result = []
    for q in questions:
        profile_data = q.get("profiles") or {}
        # 익명 질문은 작성자 이름 숨김
        author = None
        if not q.get("is_anonymous"):
            author = profile_data.get("name") if isinstance(profile_data, dict) else None

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

    res = (
        supabase.table("questions")
        .insert(
            {
                "user_id": user["id"],
                "content": body.content,
                "is_anonymous": body.is_anonymous,
            }
        )
        .execute()
    )
    q = res.data[0]

    # 작성자 이름 조회 (익명이 아닌 경우)
    author = None
    if not body.is_anonymous:
        profile_res = (
            supabase.table("profiles")
            .select("name")
            .eq("id", user["id"])
            .execute()
        )
        author = profile_res.data.get("name") if profile_res.data else None

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
    if res.data.get("user_id") != user["id"]:
        raise HTTPException(status_code=403, detail="본인의 질문만 삭제할 수 있습니다.")

    supabase.table("questions").delete().eq("id", question_id).execute()
    return {"message": "질문이 삭제되었습니다."}

