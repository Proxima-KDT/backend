from fastapi import APIRouter, HTTPException, Depends
from typing import List
from app.dependencies import get_current_user
from app.utils.supabase_client import get_supabase
from app.schemas.subject import (
    SubjectResponse,
    ConceptResponse,
    ConceptDetailResponse,
    QuizProblemResponse,
    SubjectProgressResponse,
)

router = APIRouter(prefix="/api/subjects", tags=["subjects"])


@router.get("", response_model=List[SubjectResponse])
def get_subjects(_user=Depends(get_current_user)):
    """전체 과목 목록 반환 (개념 목록 포함)"""
    supabase = get_supabase()

    subjects_res = supabase.table("subjects").select("*").execute()
    subjects = subjects_res.data or []

    concepts_res = (
        supabase.table("concepts")
        .select("id, subject_id, title, description, order_index")
        .order("order_index")
        .execute()
    )
    concepts = concepts_res.data or []

    # 과목별 문제 수 조회
    quiz_res = (
        supabase.table("concept_quiz_problems")
        .select("id, concept_id")
        .execute()
    )
    quiz_problems = quiz_res.data or []

    problems_count_by_concept: dict = {}
    for qp in quiz_problems:
        cid = qp["concept_id"]
        problems_count_by_concept[cid] = problems_count_by_concept.get(cid, 0) + 1

    concepts_by_subject: dict = {}
    for concept in concepts:
        sid = concept["subject_id"]
        concepts_by_subject.setdefault(sid, []).append(concept)

    result = []
    for subject in subjects:
        sid = subject["id"]
        subject_concepts = [
            ConceptResponse(
                id=c["id"],
                title=c["title"],
                description=c.get("description"),
                problems_count=problems_count_by_concept.get(c["id"], 0),
            )
            for c in concepts_by_subject.get(sid, [])
        ]
        result.append(
            SubjectResponse(
                id=sid,
                title=subject["title"],
                description=subject.get("description"),
                icon=subject.get("icon"),
                color=subject.get("color"),
                phase_id=subject.get("phase_id"),
                concepts=subject_concepts,
            )
        )
    return result


@router.get("/{subject_id}", response_model=SubjectResponse)
def get_subject_detail(subject_id: str, _user=Depends(get_current_user)):
    """과목 상세 조회 (개념 목록 포함)"""
    supabase = get_supabase()

    subject_res = (
        supabase.table("subjects")
        .select("*")
        .eq("id", subject_id)
        .single()
        .execute()
    )
    if not subject_res.data:
        raise HTTPException(status_code=404, detail="과목을 찾을 수 없습니다.")
    subject = subject_res.data

    concepts_res = (
        supabase.table("concepts")
        .select("id, subject_id, title, description, order_index")
        .eq("subject_id", subject_id)
        .order("order_index")
        .execute()
    )
    concepts = concepts_res.data or []

    concept_ids = [c["id"] for c in concepts]
    quiz_count_by_concept: dict = {}
    if concept_ids:
        quiz_res = (
            supabase.table("concept_quiz_problems")
            .select("id, concept_id")
            .in_("concept_id", concept_ids)
            .execute()
        )
        for qp in (quiz_res.data or []):
            cid = qp["concept_id"]
            quiz_count_by_concept[cid] = quiz_count_by_concept.get(cid, 0) + 1

    subject_concepts = [
        ConceptResponse(
            id=c["id"],
            title=c["title"],
            description=c.get("description"),
            problems_count=quiz_count_by_concept.get(c["id"], 0),
        )
        for c in concepts
    ]

    return SubjectResponse(
        id=subject["id"],
        title=subject["title"],
        description=subject.get("description"),
        icon=subject.get("icon"),
        color=subject.get("color"),
        phase_id=subject.get("phase_id"),
        concepts=subject_concepts,
    )


@router.get("/{subject_id}/progress", response_model=SubjectProgressResponse)
def get_subject_progress(subject_id: str, user=Depends(get_current_user)):
    """학생의 과목별 학습 진행률 조회"""
    supabase = get_supabase()

    # 과목 존재 확인
    subject_res = (
        supabase.table("subjects")
        .select("id")
        .eq("id", subject_id)
        .single()
        .execute()
    )
    if not subject_res.data:
        raise HTTPException(status_code=404, detail="과목을 찾을 수 없습니다.")

    # 과목 내 전체 개념 ID 조회
    concepts_res = (
        supabase.table("concepts")
        .select("id")
        .eq("subject_id", subject_id)
        .execute()
    )
    concept_ids = [c["id"] for c in (concepts_res.data or [])]

    total_problems = 0
    solved_problems = 0

    if concept_ids:
        quiz_res = (
            supabase.table("concept_quiz_problems")
            .select("id, concept_id")
            .in_("concept_id", concept_ids)
            .execute()
        )
        total_problems = len(quiz_res.data or [])

        # 사용자의 퀴즈 세션에서 맞힌 총 문제 수 집계
        sessions_res = (
            supabase.table("quiz_sessions")
            .select("correct_count")
            .eq("user_id", user["id"])
            .in_("concept_id", concept_ids)
            .execute()
        )
        solved_problems = sum(s["correct_count"] for s in (sessions_res.data or []))
        # 최대값을 total_problems로 제한
        solved_problems = min(solved_problems, total_problems)

    progress = int((solved_problems / total_problems * 100)) if total_problems > 0 else 0

    return SubjectProgressResponse(
        subject_id=subject_id,
        total_problems=total_problems,
        solved_problems=solved_problems,
        progress=progress,
    )


@router.get("/{subject_id}/concepts/{concept_id}/problems", response_model=list)
def get_concept_quiz_problems(
    subject_id: str,
    concept_id: str,
    _user=Depends(get_current_user),
):
    """개념별 퀴즈 문제 목록 반환 (정답은 제외)"""
    supabase = get_supabase()

    # comprehensive 요청 시 해당 과목 전체 문제 반환 (최대 10개)
    if concept_id == "comprehensive":
        concepts_res = (
            supabase.table("concepts")
            .select("id")
            .eq("subject_id", subject_id)
            .execute()
        )
        concept_ids = [c["id"] for c in (concepts_res.data or [])]
        if not concept_ids:
            return []
        quiz_res = (
            supabase.table("concept_quiz_problems")
            .select("id, question, choices, answer, explanation, order_index")
            .in_("concept_id", concept_ids)
            .limit(10)
            .execute()
        )
    else:
        # 개념 존재 확인
        concept_res = (
            supabase.table("concepts")
            .select("id")
            .eq("id", concept_id)
            .eq("subject_id", subject_id)
            .single()
            .execute()
        )
        if not concept_res.data:
            raise HTTPException(status_code=404, detail="개념을 찾을 수 없습니다.")

        quiz_res = (
            supabase.table("concept_quiz_problems")
            .select("id, question, choices, answer, explanation, order_index")
            .eq("concept_id", concept_id)
            .order("order_index")
            .execute()
        )

    problems = []
    for p in (quiz_res.data or []):
        problems.append(
            QuizProblemResponse(
                id=p["id"],
                question=p["question"],
                choices=p["choices"],
                answer=p.get("answer"),
                explanation=p.get("explanation"),
            )
        )
    return problems

