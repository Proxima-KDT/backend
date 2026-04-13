from fastapi import APIRouter, HTTPException, Depends
from typing import List
from app.dependencies import get_current_user
from app.utils.supabase_client import get_supabase
from app.schemas.subject import (
    SubjectResponse,
    ConceptResponse,
    QuizProblemResponse,
    SubjectProgressResponse,
    ProgressData,
)

router = APIRouter(prefix="/api/subjects", tags=["subjects"])


@router.get("", response_model=List[SubjectResponse])
def get_subjects(user=Depends(get_current_user)):
    """전체 과목 목록 반환 (개념 목록 + 진도 포함)"""
    supabase = get_supabase()

    subjects_res = supabase.table("subjects").select("*").execute()
    subjects = subjects_res.data or []

    concepts_res = (
        supabase.table("concepts")
        .select("id, subject_id, title, description, order")
        .order("order")
        .execute()
    )
    concepts = concepts_res.data or []

    # 모든 문제 조회 (subject_id, concept_id 포함)
    quiz_res = (
        supabase.table("problems")
        .select("id, subject_id, concept_id")
        .execute()
    )
    quiz_problems = quiz_res.data or []

    # 문제 집합: subject별, concept별
    problems_by_subject: dict = {}
    problems_by_concept: dict = {}
    for qp in quiz_problems:
        sid = qp.get("subject_id")
        cid = qp.get("concept_id")
        if sid:
            problems_by_subject.setdefault(sid, []).append(qp["id"])
        if cid:
            problems_by_concept.setdefault(cid, []).append(qp["id"])

    # 사용자가 푼 문제 ID 집합
    all_problem_ids = [qp["id"] for qp in quiz_problems]
    user_solved_ids: set = set()
    if all_problem_ids:
        subs_res = (
            supabase.table("submissions")
            .select("problem_id")
            .eq("user_id", user["id"])
            .in_("problem_id", all_problem_ids)
            .execute()
        )
        user_solved_ids = set(s["problem_id"] for s in (subs_res.data or []))

    concepts_by_subject: dict = {}
    for concept in concepts:
        sid = concept["subject_id"]
        concepts_by_subject.setdefault(sid, []).append(concept)

    result = []
    for subject in subjects:
        sid = subject["id"]
        subject_problem_ids = problems_by_subject.get(sid, [])
        total = len(subject_problem_ids)
        solved = len(set(subject_problem_ids) & user_solved_ids)
        percent = int((solved / total * 100)) if total > 0 else 0

        subject_concepts = []
        for c in concepts_by_subject.get(sid, []):
            cid = c["id"]
            concept_problem_ids = problems_by_concept.get(cid, [])
            c_total = len(concept_problem_ids)
            c_solved = len(set(concept_problem_ids) & user_solved_ids)
            c_percent = int((c_solved / c_total * 100)) if c_total > 0 else 0
            subject_concepts.append(
                ConceptResponse(
                    id=cid,
                    title=c["title"],
                    description=c.get("description"),
                    problems_count=c_total,
                    progress=ProgressData(solved=c_solved, total=c_total, percent=c_percent),
                )
            )
        result.append(
            SubjectResponse(
                id=sid,
                title=subject["title"],
                description=subject.get("description"),
                icon=subject.get("icon"),
                color=subject.get("color"),
                phase=subject.get("phase"),
                concepts=subject_concepts,
                progress=ProgressData(solved=solved, total=total, percent=percent),
                course_tags=subject.get("course_tags") or [],
            )
        )
    return result


@router.get("/{subject_id}", response_model=SubjectResponse)
def get_subject_detail(subject_id: str, user=Depends(get_current_user)):
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
        .select("id, subject_id, title, description, order")
        .eq("subject_id", subject_id)
        .order("order")
        .execute()
    )
    concepts = concepts_res.data or []

    concept_ids = [c["id"] for c in concepts]
    problems_by_concept: dict = {}
    quiz_count_by_concept: dict = {}

    if concept_ids:
        # 개념별 문제 조회
        quiz_res = (
            supabase.table("problems")
            .select("id, concept_id")
            .in_("concept_id", concept_ids)
            .execute()
        )
        for qp in (quiz_res.data or []):
            cid = qp["concept_id"]
            problems_by_concept.setdefault(cid, []).append(qp["id"])
            quiz_count_by_concept[cid] = quiz_count_by_concept.get(cid, 0) + 1

        # 사용자의 제출 기록 조회
        all_problem_ids = []
        for pid_list in problems_by_concept.values():
            all_problem_ids.extend(pid_list)

        user_solved: dict = {}
        if all_problem_ids:
            subs_res = (
                supabase.table("submissions")
                .select("problem_id")
                .eq("user_id", user["id"])
                .in_("problem_id", all_problem_ids)
                .execute()
            )
            # 사용자가 푼 문제 ID 집합
            user_problem_ids = set(s["problem_id"] for s in (subs_res.data or []))

            # 개념별로 푼 문제 수 계산
            for concept_id, problem_ids in problems_by_concept.items():
                solved = len(set(problem_ids) & user_problem_ids)
                user_solved[concept_id] = solved

    subject_concepts = []
    for c in concepts:
        concept_id = c["id"]
        total = quiz_count_by_concept.get(concept_id, 0)
        solved = user_solved.get(concept_id, 0)
        percent = int((solved / total * 100)) if total > 0 else 0

        subject_concepts.append(
            ConceptResponse(
                id=concept_id,
                title=c["title"],
                description=c.get("description"),
                problems_count=total,
                progress=ProgressData(
                    solved=solved,
                    total=total,
                    percent=percent
                )
            )
        )

    return SubjectResponse(
        id=subject["id"],
        title=subject["title"],
        description=subject.get("description"),
        icon=subject.get("icon"),
        color=subject.get("color"),
        phase=subject.get("phase"),
        course_tags=subject.get("course_tags") or [],
        concepts=subject_concepts,
    )


@router.get("/{subject_id}/progress", response_model=SubjectProgressResponse)
def get_subject_progress(subject_id: str, user=Depends(get_current_user)):
    """학생의 과목별 학습 진행률 조회"""
    supabase = get_supabase()

    subject_res = (
        supabase.table("subjects")
        .select("id")
        .eq("id", subject_id)
        .single()
        .execute()
    )
    if not subject_res.data:
        raise HTTPException(status_code=404, detail="과목을 찾을 수 없습니다.")

    # 과목의 전체 문제 조회
    problems_res = (
        supabase.table("problems")
        .select("id")
        .eq("subject_id", subject_id)
        .execute()
    )
    problem_ids = [p["id"] for p in (problems_res.data or [])]
    total_problems = len(problem_ids)

    solved_problems = 0
    if problem_ids:
        subs_res = (
            supabase.table("submissions")
            .select("problem_id")
            .eq("user_id", user["id"])
            .in_("problem_id", problem_ids)
            .execute()
        )
        solved_problems = len(set(s["problem_id"] for s in (subs_res.data or [])))

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
    """개념별 퀴즈 문제 목록 반환"""
    supabase = get_supabase()

    if concept_id == "comprehensive":
        quiz_res = (
            supabase.table("problems")
            .select("id, question, choices, answer, explanation")
            .eq("subject_id", subject_id)
            .limit(10)
            .execute()
        )
    else:
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
            supabase.table("problems")
            .select("id, question, choices, answer, explanation")
            .eq("concept_id", concept_id)
            .execute()
        )

    problems = []
    for p in (quiz_res.data or []):
        problems.append(
            QuizProblemResponse(
                id=p["id"],
                question=p["question"],
                choices=p.get("choices") or [],
                answer=p.get("answer"),
                explanation=p.get("explanation"),
            )
        )
    return problems

