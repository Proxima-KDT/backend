from datetime import date, datetime, timedelta, timezone
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends, Query, UploadFile, File
from app.dependencies import get_current_teacher
from app.utils.supabase_client import get_supabase
from app.schemas.teacher import (
    TeacherStudentResponse,
    TeacherCourseResponse,
    StudentFile,
    StudentNoteUpdate,
    AttendanceWeekRecord,
    ClassroomSeatResponse,
    SeatAssignRequest,
    SeatInitRequest,
    DailyAttendanceRecord,
    AttendanceStatusUpdate,
    TeacherAssignmentResponse,
    AssignmentCreateRequest,
    GradeSubmissionRequest,
    StudentSubmission,
    FileItem,
    RubricItem,
    RubricScoreItem,
    TeacherAssessmentResponse,
    AssessmentSubmission,
    AssessmentGradeRequest,
    ProblemResponse,
    ProblemCreateRequest,
    ProblemUpdateRequest,
    AIProblemGenerateRequest,
    CounselingRecordResponse,
    CounselingNoteUpdate,
    TeacherQuestionResponse,
    AnswerRequest,
)

router = APIRouter(prefix="/api/teacher", tags=["teacher"])


# ═══════════════════════════════════════════════════
# 0. 강사 담당 과정 (드롭다운)
# ═══════════════════════════════════════════════════


@router.get("/courses", response_model=List[TeacherCourseResponse])
async def list_my_courses(user=Depends(get_current_teacher)):
    """현재 로그인한 강사가 담당하는 과정 목록 — 사이드바 드롭다운용."""
    supabase = get_supabase()
    course_ids = _get_teacher_course_ids(supabase, user["id"])
    if not course_ids:
        return []

    res = (
        supabase.table("courses")
        .select("id,name,track_type,classroom")
        .in_("id", course_ids)
        .order("track_type")
        .order("name")
        .execute()
    )
    return [
        TeacherCourseResponse(
            id=c["id"],
            name=c["name"],
            track_type=c["track_type"],
            classroom=c.get("classroom"),
        )
        for c in (res.data or [])
    ]


# ═══════════════════════════════════════════════════
# 1. 학생 관리
# ═══════════════════════════════════════════════════


@router.get("/students", response_model=List[TeacherStudentResponse])
async def list_students(
    course_id: Optional[str] = Query(None),
    user=Depends(get_current_teacher),
):
    """강사 대시보드 — 담당 과정 학생 목록 (출석률, 제출률, 스킬 등) — N+1 방지: 배치 쿼리.

    course_id 쿼리 파라미터가 지정되면 해당 과정 학생만, 없으면 강사가 담당하는 모든 과정의 학생.
    """
    supabase = get_supabase()

    # 강사가 담당하는 course_id 목록 (course_id 파라미터가 있으면 권한 검증 후 단일로 좁힘)
    course_ids = _get_teacher_course_ids(supabase, user["id"], course_id)
    if not course_ids:
        return []

    profiles_res = (
        supabase.table("users")
        .select("*")
        .eq("role", "student")
        .in_("course_id", course_ids)
        .order("name")
        .execute()
    )
    students = profiles_res.data or []

    if not students:
        return []

    # course/cohort 이름 일괄 조회 (배지/응답용)
    distinct_course_ids = list({s["course_id"] for s in students if s.get("course_id")})
    distinct_cohort_ids = list({s["cohort_id"] for s in students if s.get("cohort_id")})
    course_name_map: dict = {}
    if distinct_course_ids:
        courses_res = (
            supabase.table("courses")
            .select("id,name")
            .in_("id", distinct_course_ids)
            .execute()
        )
        course_name_map = {c["id"]: c["name"] for c in (courses_res.data or [])}
    cohort_num_map: dict = {}
    if distinct_cohort_ids:
        cohorts_res = (
            supabase.table("cohorts")
            .select("id,cohort_number")
            .in_("id", distinct_cohort_ids)
            .execute()
        )
        cohort_num_map = {c["id"]: c["cohort_number"] for c in (cohorts_res.data or [])}

    student_ids = [s["id"] for s in students]

    # 동적 스킬 5축 배치 계산 (profile/skill-scores와 동일 로직 — skill_scores 테이블 stale 값 사용 안 함)
    from app.services.skill_service import calculate_students_skills_batch
    skills_by_user = calculate_students_skills_batch(supabase, student_ids)

    # 과제 제출률
    assign_res = supabase.table("assignments").select("id", count="exact").execute()
    total_assignments = assign_res.count or 0

    submitted_res = (
        supabase.table("assignment_submissions")
        .select("student_id, id", count="exact")
        .in_("student_id", student_ids)
        .neq("status", "pending")
        .execute()
    )
    files_res = (
        supabase.table("student_files")
        .select("student_id, name, type, url, uploaded_at")
        .in_("student_id", student_ids)
        .execute()
    )

    submitted_by_user: dict = {}
    for sub in (submitted_res.data or []):
        submitted_by_user[sub["student_id"]] = submitted_by_user.get(sub["student_id"], 0) + 1

    files_by_user: dict = {}
    for f in (files_res.data or []):
        files_by_user.setdefault(f["student_id"], []).append({
            "name": f.get("name", ""),
            "type": f.get("type", ""),
            "url": f.get("url", ""),
            "uploaded_at": f.get("uploaded_at", "")[:10] if f.get("uploaded_at") else None,
        })

    result = []
    for s in students:
        uid = s["id"]
        # 출결률은 스킬 출결 값과 동일 (훈련 기간 평일 대비 동적 계산)
        att_rate = float(skills_by_user.get(uid, {}).get("출결", 0))

        submitted_count = submitted_by_user.get(uid, 0)
        sub_rate = round((submitted_count / total_assignments) * 100, 1) if total_assignments > 0 else 0

        result.append(
            TeacherStudentResponse(
                id=uid,
                name=s.get("name", ""),
                email=s.get("email"),
                avatar_url=s.get("avatar_url"),
                attendance_rate=att_rate,
                submission_rate=sub_rate,
                accuracy=0,
                is_at_risk=att_rate < 80,
                last_active=s.get("updated_at", "")[:10] if s.get("updated_at") else None,
                enrolled_at=s.get("created_at", "")[:10] if s.get("created_at") else None,
                skills=skills_by_user.get(uid, {}),
                files=files_by_user.get(uid, []),
                course_id=s.get("course_id"),
                course_name=course_name_map.get(s.get("course_id")),
                cohort_id=s.get("cohort_id"),
                cohort_number=cohort_num_map.get(s.get("cohort_id")),
            )
        )
    return result


@router.get("/students/{student_id}", response_model=TeacherStudentResponse)
async def get_student_detail(student_id: str, user=Depends(get_current_teacher)):
    """학생 상세 정보"""
    supabase = get_supabase()

    profile_res = (
        supabase.table("users")
        .select("*")
        .eq("id", student_id)
        .execute()
    )
    if not profile_res.data:
        raise HTTPException(status_code=404, detail="학생을 찾을 수 없습니다.")

    s = profile_res.data[0] if isinstance(profile_res.data, list) else profile_res.data
    uid = s["id"]

    # course/cohort 메타 (배지 및 상세 렌더용)
    course_name = None
    cohort_number = None
    if s.get("course_id"):
        c_res = (
            supabase.table("courses")
            .select("name")
            .eq("id", s["course_id"])
            .limit(1)
            .execute()
        )
        if c_res.data:
            course_name = c_res.data[0].get("name")
    if s.get("cohort_id"):
        co_res = (
            supabase.table("cohorts")
            .select("cohort_number")
            .eq("id", s["cohort_id"])
            .limit(1)
            .execute()
        )
        if co_res.data:
            cohort_number = co_res.data[0].get("cohort_number")

    # 스킬 5축 동적 계산 (profile/skill-scores와 동일 로직)
    from app.services.skill_service import calculate_student_skills
    skills = calculate_student_skills(supabase, uid)
    att_rate = float(skills.get("출결", 0))

    # 제출률
    assign_res = supabase.table("assignments").select("id", count="exact").execute()
    total_assignments = assign_res.count or 0
    submitted_res = (
        supabase.table("assignment_submissions")
        .select("id", count="exact")
        .eq("student_id", uid)
        .neq("status", "pending")
        .execute()
    )
    submitted_count = submitted_res.count or 0
    sub_rate = round((submitted_count / total_assignments) * 100, 1) if total_assignments > 0 else 0

    # 파일
    files = _get_student_files(supabase, uid)

    # 상담 메모 (audio_url 없는 레코드 = 빠른 메모, 가장 최근 것)
    notes_res = (
        supabase.table("counseling_records")
        .select("summary")
        .eq("counselor_id", user["id"])
        .eq("student_id", uid)
        .is_("audio_url", "null")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    notes = notes_res.data[0]["summary"] if notes_res.data else None

    return TeacherStudentResponse(
        id=uid,
        name=s.get("name", ""),
        email=s.get("email"),
        avatar_url=s.get("avatar_url"),
        attendance_rate=att_rate,
        submission_rate=sub_rate,
        accuracy=0,
        is_at_risk=att_rate < 80,
        last_active=s.get("updated_at", "")[:10] if s.get("updated_at") else None,
        enrolled_at=s.get("created_at", "")[:10] if s.get("created_at") else None,
        notes=notes,
        skills=skills,
        files=files,
        course_id=s.get("course_id"),
        course_name=course_name,
        cohort_id=s.get("cohort_id"),
        cohort_number=cohort_number,
    )


@router.get("/students/{student_id}/attendance/week")
async def get_student_weekly_attendance(
    student_id: str,
    date_str: str = Query(None, alias="date"),
    user=Depends(get_current_teacher),
):
    """학생 주간 출결 조회 (7일)"""
    supabase = get_supabase()

    base_date = date.fromisoformat(date_str) if date_str else date.today()
    monday = base_date - timedelta(days=base_date.weekday())
    sunday = monday + timedelta(days=6)

    res = (
        supabase.table("attendance")
        .select("date, status, check_in_time")
        .eq("user_id", student_id)
        .gte("date", monday.isoformat())
        .lte("date", sunday.isoformat())
        .order("date")
        .execute()
    )
    records_map = {r["date"]: r for r in (res.data or [])}

    result = []
    for i in range(7):
        d = (monday + timedelta(days=i)).isoformat()
        rec = records_map.get(d)
        result.append({
            "date": d,
            "status": rec.get("status") if rec else None,
            "time": rec.get("check_in_time") if rec else None,
        })
    return result


@router.patch("/students/{student_id}/notes")
async def update_student_notes(
    student_id: str, body: StudentNoteUpdate, user=Depends(get_current_teacher)
):
    """학생 상담 메모 저장/수정 — counseling_records의 기존 메모 레코드 upsert"""
    supabase = get_supabase()

    student_res = supabase.table("users").select("name").eq("id", student_id).execute()
    student_name = student_res.data[0]["name"] if student_res.data else ""

    # audio_url이 없는 레코드 = 빠른 메모 (음성 상담 기록과 구분)
    existing = (
        supabase.table("counseling_records")
        .select("id")
        .eq("counselor_id", user["id"])
        .eq("student_id", student_id)
        .is_("audio_url", "null")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )

    if existing.data:
        supabase.table("counseling_records").update({
            "summary": body.notes,
            "date": date.today().isoformat(),
        }).eq("id", existing.data[0]["id"]).execute()
    else:
        supabase.table("counseling_records").insert({
            "student_id": student_id,
            "student_name": student_name,
            "counselor_id": user["id"],
            "date": date.today().isoformat(),
            "summary": body.notes,
        }).execute()

    return {"message": "상담 메모가 저장되었습니다."}


# ═══════════════════════════════════════════════════
# 2. 출결 관리
# ═══════════════════════════════════════════════════


@router.get("/classroom/seats", response_model=List[ClassroomSeatResponse])
async def get_classroom_seats(
    course_id: str = Query(..., description="조회할 과정 ID"),
    user=Depends(get_current_teacher),
):
    """교실 좌석 배치도 조회 — 지정한 과정의 좌석만 반환."""
    supabase = get_supabase()

    # 권한: 본인이 담당하는 과정만 허용
    if not _teacher_owns_course(supabase, user["id"], course_id):
        raise HTTPException(status_code=403, detail="담당하지 않는 과정입니다.")

    res = (
        supabase.table("classroom_seats")
        .select("*")
        .eq("course_id", course_id)
        .order("row")
        .order("col")
        .execute()
    )
    seats = res.data or []

    # 배정된 학생 이름 일괄 조회 (N+1 방지)
    student_ids = [s["student_id"] for s in seats if s.get("student_id")]
    student_names: dict = {}
    if student_ids:
        users_res = (
            supabase.table("users")
            .select("id, name")
            .in_("id", student_ids)
            .execute()
        )
        student_names = {u["id"]: u["name"] for u in (users_res.data or [])}

    return [
        ClassroomSeatResponse(
            seat_id=s["seat_id"],
            row=s["row"],
            col=s["col"],
            course_id=s.get("course_id"),
            student_id=s.get("student_id"),
            student_name=student_names.get(s.get("student_id", "")),
        )
        for s in seats
    ]


@router.patch("/classroom/seats/{seat_id}/assign", response_model=ClassroomSeatResponse)
async def assign_seat(
    seat_id: str, body: SeatAssignRequest, user=Depends(get_current_teacher)
):
    """좌석에 학생 배정 / 이동 / 해제 (드래그앤드롭 저장).

    좌석은 과정에 귀속되므로:
    - 대상 좌석이 강사의 담당 과정에 속하는지 확인
    - 같은 과정 내에서만 학생 이동 허용 (다른 과정 좌석은 건드리지 않음)
    """
    supabase = get_supabase()

    seat_res = (
        supabase.table("classroom_seats")
        .select("*")
        .eq("seat_id", seat_id)
        .execute()
    )
    if not seat_res.data:
        raise HTTPException(status_code=404, detail="좌석을 찾을 수 없습니다.")
    seat_row = seat_res.data[0]
    seat_course_id = seat_row.get("course_id")

    if not _teacher_owns_course(supabase, user["id"], seat_course_id):
        raise HTTPException(status_code=403, detail="담당하지 않는 과정의 좌석입니다.")

    # 같은 학생이 같은 과정 내 다른 자리에 이미 배정되어 있으면 먼저 해제
    if body.student_id:
        existing = (
            supabase.table("classroom_seats")
            .select("seat_id")
            .eq("student_id", body.student_id)
            .eq("course_id", seat_course_id)
            .execute()
        )
        for prev in (existing.data or []):
            if prev["seat_id"] != seat_id:
                supabase.table("classroom_seats").update(
                    {"student_id": None}
                ).eq("seat_id", prev["seat_id"]).execute()

    supabase.table("classroom_seats").update(
        {"student_id": body.student_id}
    ).eq("seat_id", seat_id).execute()

    res = (
        supabase.table("classroom_seats")
        .select("*")
        .eq("seat_id", seat_id)
        .execute()
    )
    s = res.data[0]
    student_name = None
    if s.get("student_id"):
        u = (
            supabase.table("users")
            .select("name")
            .eq("id", s["student_id"])
            .execute()
        )
        student_name = u.data[0]["name"] if u.data else None

    return ClassroomSeatResponse(
        seat_id=s["seat_id"],
        row=s["row"],
        col=s["col"],
        course_id=s.get("course_id"),
        student_id=s.get("student_id"),
        student_name=student_name,
    )


@router.post("/classroom/seats/init")
async def init_classroom_seats(
    body: SeatInitRequest,
    user=Depends(get_current_teacher),
):
    """특정 과정의 빈 좌석을 초기화. 해당 과정의 기존 좌석은 전부 삭제 후 재생성."""
    supabase = get_supabase()

    if not _teacher_owns_course(supabase, user["id"], body.course_id):
        raise HTTPException(status_code=403, detail="담당하지 않는 과정입니다.")

    supabase.table("classroom_seats").delete().eq("course_id", body.course_id).execute()

    rows, cols = body.rows, body.cols
    seats = [
        {
            "seat_id": f"{body.course_id}-R{r}C{c}",
            "row": r,
            "col": c,
            "course_id": body.course_id,
            "student_id": None,
        }
        for r in range(1, rows + 1)
        for c in range(1, cols + 1)
    ]
    supabase.table("classroom_seats").insert(seats).execute()
    return {"message": f"{body.course_id} 좌석 {len(seats)}개가 초기화되었습니다.", "count": len(seats)}


@router.get("/attendance/{date_str}", response_model=List[DailyAttendanceRecord])
async def get_daily_attendance(
    date_str: str,
    course_id: Optional[str] = Query(None),
    user=Depends(get_current_teacher),
):
    """일별 출석 현황 조회 — 담당 과정 학생만. course_id로 단일 과정 필터링 가능."""
    supabase = get_supabase()

    course_ids = _get_teacher_course_ids(supabase, user["id"], course_id)
    if not course_ids:
        return []

    att_res = (
        supabase.table("attendance")
        .select("user_id, status, check_in_time")
        .eq("date", date_str)
        .execute()
    )
    att_map = {a["user_id"]: a for a in (att_res.data or [])}

    # 좌석도 과정 기준으로 필터 (같은 학생이 여러 과정에 좌석이 있을 가능성 방지)
    seats_q = supabase.table("classroom_seats").select("*").in_("course_id", course_ids)
    seats_res = seats_q.execute()
    seats_map = {}
    for seat in (seats_res.data or []):
        if seat.get("student_id"):
            seats_map[seat["student_id"]] = seat.get("seat_id")

    students_res = (
        supabase.table("users")
        .select("id, name")
        .eq("role", "student")
        .in_("course_id", course_ids)
        .execute()
    )

    result = []
    for student in (students_res.data or []):
        uid = student["id"]
        att = att_map.get(uid, {})
        result.append(
            DailyAttendanceRecord(
                student_id=uid,
                student_name=student.get("name", ""),
                seat_id=seats_map.get(uid),
                status=att.get("status", "absent"),
                check_in_time=att.get("check_in_time"),
            )
        )
    return result


@router.patch("/attendance/{date_str}/{student_id}")
async def update_attendance_status(
    date_str: str,
    student_id: str,
    body: AttendanceStatusUpdate,
    user=Depends(get_current_teacher),
):
    """학생 출석 상태 수정 — 담당 과정 학생만 허용."""
    supabase = get_supabase()

    # 권한: 해당 학생이 강사의 담당 과정 소속인지 확인
    stu_res = (
        supabase.table("users")
        .select("course_id")
        .eq("id", student_id)
        .limit(1)
        .execute()
    )
    if not stu_res.data:
        raise HTTPException(status_code=404, detail="학생을 찾을 수 없습니다.")
    stu_course_id = stu_res.data[0].get("course_id")
    if not _teacher_owns_course(supabase, user["id"], stu_course_id):
        raise HTTPException(status_code=403, detail="담당하지 않는 과정의 학생입니다.")

    existing = (
        supabase.table("attendance")
        .select("id")
        .eq("user_id", student_id)
        .eq("date", date_str)
        .execute()
    )

    if existing.data:
        existing_rec = existing.data[0] if isinstance(existing.data, list) else existing.data
        supabase.table("attendance").update(
            {"status": body.status}
        ).eq("id", existing_rec["id"]).execute()
    else:
        supabase.table("attendance").insert({
            "user_id": student_id,
            "date": date_str,
            "status": body.status,
        }).execute()

    return {"message": "출석 상태가 업데이트되었습니다.", "status": body.status}


# ═══════════════════════════════════════════════════
# 3. 과제 관리
# ═══════════════════════════════════════════════════


@router.get("/assignments", response_model=List[TeacherAssignmentResponse])
async def list_teacher_assignments(
    course_id: Optional[str] = Query(None),
    user=Depends(get_current_teacher),
):
    """과제 목록 + 학생 제출 현황 — 담당 과정 학생만."""
    supabase = get_supabase()

    assignments_res = (
        supabase.table("assignments")
        .select("*")
        .order("due_date", desc=True)
        .execute()
    )
    assignments = assignments_res.data or []
    students = _get_teacher_students(supabase, user["id"], course_id)

    result = []
    for a in assignments:
        aid = str(a["id"])

        subs_res = (
            supabase.table("assignment_submissions")
            .select("*")
            .eq("assignment_id", aid)
            .execute()
        )
        subs_map = {str(sub["student_id"]): sub for sub in (subs_res.data or [])}

        student_submissions = []
        for student in students:
            sid = student["id"]
            sub = subs_map.get(sid)
            sub_files = []
            if sub and sub.get("files"):
                sub_files = [
                    FileItem(name=f.get("name", ""), url=f.get("path"))
                    for f in (sub["files"] if isinstance(sub["files"], list) else [])
                ]
            student_submissions.append(
                StudentSubmission(
                    studentId=sid,
                    studentName=student.get("name", ""),
                    status=sub["status"] if sub else "pending",
                    submittedAt=sub.get("submitted_at") if sub else None,
                    files=sub_files,
                    score=sub.get("score") if sub else None,
                    feedback=sub.get("feedback") if sub else None,
                    rubricScores=sub.get("rubric_scores") if sub else None,
                )
            )

        rubric_data = a.get("rubric") or []
        rubric_items = []
        for r in rubric_data:
            if isinstance(r, dict):
                rubric_items.append(RubricItem(item=r.get("item", ""), maxScore=r.get("maxScore", 0)))

        result.append(
            TeacherAssignmentResponse(
                id=aid,
                title=a["title"],
                subject=a.get("subject"),
                phase=a.get("phase"),
                description=a.get("description"),
                dueDate=a.get("due_date"),
                openDate=a.get("open_date"),
                maxScore=a.get("max_score", 100),
                attachments=[],
                rubric=rubric_items,
                studentSubmissions=student_submissions,
            )
        )
    return result


@router.post("/assignments")
async def create_assignment(body: AssignmentCreateRequest, user=Depends(get_current_teacher)):
    """새 과제 생성"""
    supabase = get_supabase()

    rubric_data = [{"item": r.item, "maxScore": r.maxScore} for r in body.rubric]

    # Phase에서 subject 자동 도출 (프론트에서 보내주지만 백엔드에서도 보장)
    phase_subject_map = {
        1: "Python 기초",
        2: "JavaScript & React",
        3: "DB & SQL",
        4: "알고리즘 & 자료구조",
        5: "풀스택 프로젝트",
        6: "ML/DL & 취업준비",
    }
    subject = body.subject or phase_subject_map.get(body.phase, "")

    res = (
        supabase.table("assignments")
        .insert({
            "title": body.title,
            "subject": subject,
            "phase": body.phase,
            "description": body.description,
            "open_date": body.openDate,
            "due_date": body.dueDate,
            "max_score": body.maxScore,
            "rubric": rubric_data,
            "created_by": user["id"],
        })
        .execute()
    )
    return {"message": "과제가 생성되었습니다.", "id": str(res.data[0]["id"])}


@router.get("/assignments/{assignment_id}", response_model=TeacherAssignmentResponse)
async def get_teacher_assignment_detail(
    assignment_id: str,
    course_id: Optional[str] = Query(None),
    user=Depends(get_current_teacher),
):
    """과제 상세 + 제출 현황 — 담당 과정 학생만."""
    supabase = get_supabase()

    a_res = (
        supabase.table("assignments")
        .select("*")
        .eq("id", assignment_id)
        .execute()
    )
    if not a_res.data:
        raise HTTPException(status_code=404, detail="과제를 찾을 수 없습니다.")

    a = a_res.data[0] if isinstance(a_res.data, list) else a_res.data
    students = _get_teacher_students(supabase, user["id"], course_id)

    subs_res = (
        supabase.table("assignment_submissions")
        .select("*")
        .eq("assignment_id", assignment_id)
        .execute()
    )
    subs_map = {str(sub["student_id"]): sub for sub in (subs_res.data or [])}

    student_submissions = []
    for student in students:
        sid = student["id"]
        sub = subs_map.get(sid)
        student_submissions.append(
            StudentSubmission(
                studentId=sid,
                studentName=student.get("name", ""),
                status=sub["status"] if sub else "pending",
                submittedAt=sub.get("submitted_at") if sub else None,
                files=[],
                score=sub.get("score") if sub else None,
                feedback=sub.get("feedback") if sub else None,
                rubricScores=sub.get("rubric_scores") if sub else None,
            )
        )

    rubric_data = a.get("rubric") or []
    rubric_items = []
    for r in rubric_data:
        if isinstance(r, dict):
            rubric_items.append(RubricItem(item=r.get("item", ""), maxScore=r.get("maxScore", 0)))

    return TeacherAssignmentResponse(
        id=str(a["id"]),
        title=a["title"],
        subject=a.get("subject"),
        phase=a.get("phase"),
        description=a.get("description"),
        dueDate=a.get("due_date"),
        openDate=a.get("open_date"),
        maxScore=a.get("max_score", 100),
        attachments=[],
        rubric=rubric_items,
        studentSubmissions=student_submissions,
    )


@router.patch("/assignments/{assignment_id}/submissions/{student_id}")
async def grade_assignment_submission(
    assignment_id: str,
    student_id: str,
    body: GradeSubmissionRequest,
    user=Depends(get_current_teacher),
):
    """과제 채점 — 점수, 피드백, 루브릭 점수 저장"""
    supabase = get_supabase()

    existing = (
        supabase.table("assignment_submissions")
        .select("id")
        .eq("assignment_id", assignment_id)
        .eq("student_id", student_id)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail="제출 기록을 찾을 수 없습니다.")

    update_data = {
        "feedback": body.feedback,
        "status": body.status,
    }
    if body.score is not None:
        update_data["score"] = body.score
    if body.rubricScores:
        update_data["rubric_scores"] = [
            {"item": rs.item, "score": rs.score, "maxScore": rs.maxScore}
            for rs in body.rubricScores
        ]

    existing_rec = existing.data[0] if isinstance(existing.data, list) else existing.data
    supabase.table("assignment_submissions").update(update_data).eq(
        "id", existing_rec["id"]
    ).execute()

    return {"message": "채점이 완료되었습니다."}


@router.post("/assignments/{assignment_id}/submissions/{student_id}/ai-feedback")
async def ai_feedback_assignment(
    assignment_id: str, student_id: str, user=Depends(get_current_teacher)
):
    """과제 제출 파일을 AI가 읽고 루브릭 채점 + 피드백 생성 (저장하지 않음, 초안 반환)."""
    supabase = get_supabase()

    # 과제 정보
    assign_res = (
        supabase.table("assignments")
        .select("title, description, rubric")
        .eq("id", assignment_id)
        .execute()
    )
    if not assign_res.data:
        raise HTTPException(status_code=404, detail="과제를 찾을 수 없습니다.")
    assign = assign_res.data[0] if isinstance(assign_res.data, list) else assign_res.data

    # 학생 제출 정보 (files 컬럼)
    sub_res = (
        supabase.table("assignment_submissions")
        .select("files")
        .eq("assignment_id", assignment_id)
        .eq("student_id", student_id)
        .execute()
    )
    if not sub_res.data:
        raise HTTPException(status_code=404, detail="제출 기록을 찾을 수 없습니다.")
    sub = sub_res.data[0] if isinstance(sub_res.data, list) else sub_res.data

    # 파일 URL 목록 추출 — path는 Storage 버킷 내부 경로이므로 signed URL로 변환
    raw_files = sub.get("files") or []
    # (원본 파일명, signed URL) 쌍으로 관리 — GPT에 의미있는 파일명 전달
    file_items: list[tuple[str, str]] = []
    if isinstance(raw_files, list):
        for f in raw_files:
            if not isinstance(f, dict):
                continue
            bucket_path = f.get("path") or f.get("url", "")
            original_name = f.get("name", "") or bucket_path.split("/")[-1]
            if not bucket_path:
                continue
            if bucket_path.startswith("http"):
                file_items.append((original_name, bucket_path))
            else:
                try:
                    signed = supabase.storage.from_("uploads").create_signed_url(
                        bucket_path, expires_in=300  # 5분 유효
                    )
                    url = signed.get("signedURL") or signed.get("signed_url") or ""
                    if url:
                        file_items.append((original_name, url))
                except Exception:
                    pass  # 서명 실패한 파일은 건너뜀

    rubric = assign.get("rubric") or []

    from app.services.ai_service import grade_assignment_submission
    result = await grade_assignment_submission(
        assignment_title=assign.get("title", ""),
        assignment_description=assign.get("description", ""),
        rubric=rubric,
        file_items=file_items,
    )

    return {
        "rubricScores": result["rubric_scores"],
        "totalScore": result["total_score"],
        "feedback": result["feedback"],
        "filesRead": len(file_items),
    }


@router.get("/assignments/{assignment_id}/submissions/{student_id}/download-urls")
async def get_submission_download_urls(
    assignment_id: str, student_id: str, user=Depends(get_current_teacher)
):
    """제출 파일의 다운로드용 signed URL 목록 반환 (5분 유효)"""
    supabase = get_supabase()

    sub_res = (
        supabase.table("assignment_submissions")
        .select("files")
        .eq("assignment_id", assignment_id)
        .eq("student_id", student_id)
        .execute()
    )
    if not sub_res.data:
        raise HTTPException(status_code=404, detail="제출 기록을 찾을 수 없습니다.")
    sub = sub_res.data[0] if isinstance(sub_res.data, list) else sub_res.data

    raw_files = sub.get("files") or []
    result = []
    for f in (raw_files if isinstance(raw_files, list) else []):
        if not isinstance(f, dict):
            continue
        bucket_path = f.get("path", "")
        name = f.get("name", bucket_path.split("/")[-1])
        if not bucket_path:
            continue
        if bucket_path.startswith("http"):
            result.append({"name": name, "url": bucket_path})
        else:
            try:
                signed = supabase.storage.from_("uploads").create_signed_url(
                    bucket_path, expires_in=300
                )
                url = signed.get("signedURL") or signed.get("signed_url") or ""
                if url:
                    result.append({"name": name, "url": url})
            except Exception:
                pass

    return {"files": result}


@router.delete("/assignments/{assignment_id}")
async def delete_assignment(assignment_id: str, user=Depends(get_current_teacher)):
    """과제 삭제"""
    supabase = get_supabase()

    res = (
        supabase.table("assignments")
        .select("id")
        .eq("id", assignment_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="과제를 찾을 수 없습니다.")

    supabase.table("assignments").delete().eq("id", assignment_id).execute()
    return {"message": "과제가 삭제되었습니다."}


# ═══════════════════════════════════════════════════
# 4. 평가 관리
# ═══════════════════════════════════════════════════


@router.get("/assessments", response_model=List[TeacherAssessmentResponse])
async def list_teacher_assessments(
    course_id: Optional[str] = Query(None),
    user=Depends(get_current_teacher),
):
    """평가 목록 + 학생 제출 현황 — 담당 과정 학생만."""
    supabase = get_supabase()

    assessments_res = (
        supabase.table("assessments")
        .select("*")
        .order("phase_id")
        .execute()
    )
    assessments = assessments_res.data or []
    students = _get_teacher_students(supabase, user["id"], course_id)

    result = []
    for a in assessments:
        aid = str(a["id"])

        subs_res = (
            supabase.table("assessment_submissions")
            .select("*")
            .eq("assessment_id", aid)
            .execute()
        )
        subs_map = {str(sub["student_id"]): sub for sub in (subs_res.data or [])}

        student_submissions = []
        for student in students:
            sid = student["id"]
            sub = subs_map.get(sid)
            # 제출된 파일 목록 (name/path만, signed URL은 download-urls 엔드포인트에서 발급)
            sub_files = []
            if sub and sub.get("files"):
                for f in (sub["files"] if isinstance(sub["files"], list) else []):
                    if not isinstance(f, dict):
                        continue
                    sub_files.append(
                        FileItem(
                            name=f.get("name", f.get("path", "").split("/")[-1]),
                            size=f.get("size"),
                            url=f.get("path", ""),
                        )
                    )
            student_submissions.append(
                AssessmentSubmission(
                    studentId=sid,
                    studentName=student.get("name", ""),
                    status=sub["status"] if sub else "pending",
                    submittedAt=sub.get("submitted_at") if sub else None,
                    files=sub_files,
                    score=sub.get("score") if sub else None,
                    passed=sub.get("passed") if sub else None,
                    feedback=sub.get("feedback") if sub else None,
                    rubricScores=sub.get("rubric") if sub else None,
                )
            )

        rubric_data = a.get("rubric") or []
        rubric_items = []
        for r in rubric_data:
            if isinstance(r, dict):
                rubric_items.append(RubricItem(item=r.get("item", ""), maxScore=r.get("maxScore", 0)))

        result.append(
            TeacherAssessmentResponse(
                id=aid,
                phaseId=a.get("phase_id"),
                phaseTitle=a.get("phase_title"),
                title=a.get("title"),
                subject=a.get("subject"),
                description=a.get("description"),
                period={"start": a.get("period_start"), "end": a.get("period_end")},
                maxScore=a.get("max_score", 100),
                passScore=a.get("pass_score", 60),
                rubric=rubric_items,
                studentSubmissions=student_submissions,
            )
        )
    return result


@router.get("/assessments/{assessment_id}/submissions/{student_id}/download-urls")
async def get_assessment_submission_download_urls(
    assessment_id: str, student_id: str, user=Depends(get_current_teacher)
):
    """평가 제출 파일의 다운로드용 signed URL 목록 반환 (5분 유효)"""
    supabase = get_supabase()

    sub_res = (
        supabase.table("assessment_submissions")
        .select("files")
        .eq("assessment_id", assessment_id)
        .eq("student_id", student_id)
        .execute()
    )
    if not sub_res.data:
        raise HTTPException(status_code=404, detail="제출 기록을 찾을 수 없습니다.")
    sub = sub_res.data[0]

    raw_files = sub.get("files") or []
    result = []
    for f in (raw_files if isinstance(raw_files, list) else []):
        if not isinstance(f, dict):
            continue
        bucket_path = f.get("path", "")
        name = f.get("name", bucket_path.split("/")[-1])
        if not bucket_path:
            continue
        if bucket_path.startswith("http"):
            result.append({"name": name, "url": bucket_path})
        else:
            try:
                signed = supabase.storage.from_("uploads").create_signed_url(
                    bucket_path, expires_in=300
                )
                url = signed.get("signedURL") or signed.get("signed_url") or ""
                if url:
                    result.append({"name": name, "url": url})
            except Exception:
                pass

    return {"files": result}


@router.post("/assessments/{assessment_id}/submissions/{student_id}/ai-score")
async def ai_grade_assessment(
    assessment_id: str, student_id: str, user=Depends(get_current_teacher)
):
    """AI 자동 채점 (GPT-4o-mini) — 루브릭 항목별 점수 + 종합 피드백 반환 (저장 안 함, 초안)"""
    supabase = get_supabase()

    assessment_res = (
        supabase.table("assessments")
        .select("*")
        .eq("id", assessment_id)
        .execute()
    )
    if not assessment_res.data:
        raise HTTPException(status_code=404, detail="평가를 찾을 수 없습니다.")

    sub_res = (
        supabase.table("assessment_submissions")
        .select("*")
        .eq("assessment_id", assessment_id)
        .eq("student_id", student_id)
        .execute()
    )
    if not sub_res.data:
        raise HTTPException(status_code=404, detail="제출 기록을 찾을 수 없습니다.")

    # Bug fix: .data는 리스트, [0]으로 단건 추출
    assessment = assessment_res.data[0]
    sub_record = sub_res.data[0]
    rubric = assessment.get("rubric") or []

    # 제출 파일 signed URL 준비
    raw_files = sub_record.get("files") or []
    file_items: list[tuple[str, str]] = []
    if isinstance(raw_files, list):
        for f in raw_files:
            if not isinstance(f, dict):
                continue
            bucket_path = f.get("path") or f.get("url", "")
            original_name = f.get("name", "") or bucket_path.split("/")[-1]
            if not bucket_path:
                continue
            if bucket_path.startswith("http"):
                file_items.append((original_name, bucket_path))
            else:
                try:
                    signed = supabase.storage.from_("uploads").create_signed_url(
                        bucket_path, expires_in=300
                    )
                    url = signed.get("signedURL") or signed.get("signed_url") or ""
                    if url:
                        file_items.append((original_name, url))
                except Exception:
                    pass

    from app.services.ai_service import grade_assessment
    ai_result = await grade_assessment(
        assessment_description=assessment.get("description", ""),
        rubric=rubric,
        max_score=assessment.get("max_score", 100),
        file_items=file_items,
    )

    pass_score = assessment.get("pass_score", 60)
    passed = ai_result["score"] >= pass_score

    return {
        "score": ai_result["score"],
        "passed": passed,
        "rubric_scores": ai_result.get("rubric_scores", []),
        "feedback": ai_result["feedback"],
    }


@router.patch("/assessments/{assessment_id}/submissions/{student_id}")
async def confirm_assessment_grade(
    assessment_id: str,
    student_id: str,
    body: AssessmentGradeRequest,
    user=Depends(get_current_teacher),
):
    """평가 점수 확정/수정"""
    supabase = get_supabase()

    existing = (
        supabase.table("assessment_submissions")
        .select("id")
        .eq("assessment_id", assessment_id)
        .eq("student_id", student_id)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail="제출 기록을 찾을 수 없습니다.")

    update_data = {
        "score": body.score,
        "feedback": body.feedback,
        "status": "graded",
    }
    if body.passed is not None:
        update_data["passed"] = body.passed
    if body.rubricScores:
        update_data["rubric"] = [
            {"item": rs.item, "score": rs.score, "maxScore": rs.maxScore}
            for rs in body.rubricScores
        ]

    existing_rec = existing.data[0] if isinstance(existing.data, list) else existing.data
    supabase.table("assessment_submissions").update(update_data).eq(
        "id", existing_rec["id"]
    ).execute()

    return {"message": "평가 점수가 확정되었습니다."}


# ═══════════════════════════════════════════════════
# 5. 문제 관리
# ═══════════════════════════════════════════════════


@router.get("/problems", response_model=List[ProblemResponse])
async def list_teacher_problems(
    difficulty: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    user=Depends(get_current_teacher),
):
    """문제 목록 조회 (필터 지원)"""
    supabase = get_supabase()

    query = supabase.table("problems").select("*").order("created_at", desc=True)
    if difficulty:
        query = query.eq("difficulty", difficulty)
    if type:
        query = query.eq("type", type)

    res = query.execute()
    problems = res.data or []

    return [
        ProblemResponse(
            id=p["id"],
            title=p["title"],
            description=p.get("description"),
            type=p["type"],
            difficulty=p.get("difficulty"),
            tags=p.get("tags") or [],
            choices=p.get("choices"),
            correct_answer=p.get("answer"),
            concept_id=p.get("concept_id"),
            created_at=p.get("created_at"),
        )
        for p in problems
    ]


@router.post("/problems")
async def create_problem(body: ProblemCreateRequest, user=Depends(get_current_teacher)):
    """문제 생성"""
    supabase = get_supabase()

    payload = {
        "title": body.title,
        "description": body.description,
        "type": body.type,
        "difficulty": body.difficulty,
        "tags": body.tags,
        "answer": body.correct_answer,
    }
    if body.choices:
        payload["choices"] = body.choices
    if body.concept_id:
        payload["concept_id"] = body.concept_id

    res = supabase.table("problems").insert(payload).execute()
    return {"message": "문제가 생성되었습니다.", "id": res.data[0]["id"]}


@router.patch("/problems/{problem_id}")
async def update_problem(
    problem_id: str, body: ProblemUpdateRequest, user=Depends(get_current_teacher)
):
    """문제 수정"""
    supabase = get_supabase()

    existing = (
        supabase.table("problems")
        .select("id")
        .eq("id", problem_id)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail="문제를 찾을 수 없습니다.")

    update_data = {}
    if body.title is not None:
        update_data["title"] = body.title
    if body.description is not None:
        update_data["description"] = body.description
    if body.type is not None:
        update_data["type"] = body.type
    if body.difficulty is not None:
        update_data["difficulty"] = body.difficulty
    if body.tags is not None:
        update_data["tags"] = body.tags
    if body.choices is not None:
        update_data["choices"] = body.choices
    if body.correct_answer is not None:
        update_data["answer"] = body.correct_answer

    if update_data:
        supabase.table("problems").update(update_data).eq("id", problem_id).execute()

    return {"message": "문제가 수정되었습니다."}


@router.delete("/problems/{problem_id}")
async def delete_problem(problem_id: str, user=Depends(get_current_teacher)):
    """문제 삭제"""
    supabase = get_supabase()

    existing = (
        supabase.table("problems")
        .select("id")
        .eq("id", problem_id)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail="문제를 찾을 수 없습니다.")

    supabase.table("problems").delete().eq("id", problem_id).execute()
    return {"message": "문제가 삭제되었습니다."}


@router.post("/problems/generate-ai")
async def generate_problems_ai(
    body: AIProblemGenerateRequest, user=Depends(get_current_teacher)
):
    """AI 문제 자동 생성 (GPT-4o-mini)"""
    from app.services.ai_service import generate_problems

    problems = await generate_problems(
        topic=body.topic,
        difficulty=body.difficulty,
        count=body.count,
        problem_type=body.type,
    )

    supabase = get_supabase()
    created_ids = []
    for p in problems:
        res = (
            supabase.table("problems")
            .insert({
                "title": p["title"],
                "description": p.get("description"),
                "type": p["type"],
                "difficulty": body.difficulty,
                "tags": p.get("tags", []),
                "choices": p.get("choices"),
                "answer": p.get("correct_answer"),
            })
            .execute()
        )
        created_ids.append(res.data[0]["id"])

    return {"message": f"{len(created_ids)}개 문제가 생성되었습니다.", "ids": created_ids}


# ═══════════════════════════════════════════════════
# 6. 상담 (오디오 업로드 + 기록 조회)
# ═══════════════════════════════════════════════════


@router.post("/counseling/upload")
async def upload_counseling_audio(
    file: UploadFile = File(...),
    student_name: str = Query(...),
    user=Depends(get_current_teacher),
):
    """상담 오디오 업로드 → Supabase Storage 저장 → Whisper STT → AI 요약"""
    from app.services.stt_service import transcribe_audio
    from app.services.ai_service import summarize_counseling

    audio_bytes = await file.read()
    supabase = get_supabase()

    # Supabase Storage에 오디오 파일 저장
    today_str = date.today().isoformat()
    safe_filename = file.filename.replace(" ", "_") if file.filename else "audio.mp3"
    storage_path = f"counseling/{user['id']}/{today_str}_{safe_filename}"
    content_type = file.content_type or "audio/mpeg"

    audio_url = None
    try:
        supabase.storage.from_("uploads").upload(
            storage_path,
            audio_bytes,
            {"content-type": content_type},
        )
        audio_url = supabase.storage.from_("uploads").get_public_url(storage_path)
    except Exception:
        # Storage 업로드 실패해도 STT/요약은 계속 진행
        pass

    # Whisper STT
    transcript = await transcribe_audio(audio_bytes, file.filename or safe_filename)

    # AI 요약 (GPT 기반 내용 요약 + 화자 추출)
    summary_result = await summarize_counseling(transcript)

    # DB 저장
    res = (
        supabase.table("counseling_records")
        .insert({
            "counselor_id": user["id"],
            "student_name": student_name,
            "date": today_str,
            "duration": summary_result.get("duration"),
            "transcript": transcript,
            "summary": summary_result.get("summary"),
            "action_items": summary_result.get("action_items", []),
            "speakers": summary_result.get("speakers", []),
            "audio_url": audio_url,
        })
        .execute()
    )

    record = res.data[0]
    return {
        "id": str(record["id"]),
        "student_name": student_name,
        "date": today_str,
        "duration": summary_result.get("duration"),
        "summary": summary_result.get("summary"),
        "action_items": summary_result.get("action_items", []),
        "speakers": summary_result.get("speakers", []),
        "audio_url": audio_url,
    }


@router.get("/counseling-records", response_model=List[CounselingRecordResponse])
async def list_counseling_records(user=Depends(get_current_teacher)):
    """상담 기록 목록 — 담당 학생의 수강 과정명을 함께 반환(배지용)."""
    supabase = get_supabase()

    res = (
        supabase.table("counseling_records")
        .select("*")
        .eq("counselor_id", user["id"])
        .order("date", desc=True)
        .execute()
    )
    records = res.data or []

    # course_name 배지용: student_id → course_id → course.name 맵 빌드
    student_ids = list({r["student_id"] for r in records if r.get("student_id")})
    student_course_map: dict = {}
    course_name_map: dict = {}
    if student_ids:
        stu_res = (
            supabase.table("users")
            .select("id,course_id")
            .in_("id", student_ids)
            .execute()
        )
        student_course_map = {u["id"]: u.get("course_id") for u in (stu_res.data or [])}
        distinct_course_ids = list({cid for cid in student_course_map.values() if cid})
        if distinct_course_ids:
            c_res = (
                supabase.table("courses")
                .select("id,name")
                .in_("id", distinct_course_ids)
                .execute()
            )
            course_name_map = {c["id"]: c["name"] for c in (c_res.data or [])}

    return [
        CounselingRecordResponse(
            id=str(r["id"]),
            student_id=str(r["student_id"]) if r.get("student_id") else None,
            student_name=r.get("student_name"),
            course_name=course_name_map.get(student_course_map.get(r.get("student_id"))),
            date=r.get("date", ""),
            duration=r.get("duration"),
            summary=r.get("summary"),
            action_items=r.get("action_items") or [],
            speakers=r.get("speakers") or [],
            audio_url=r.get("audio_url"),
            note=r.get("note"),
        )
        for r in records
    ]


@router.patch("/counseling-records/{record_id}/note")
async def update_counseling_note(
    record_id: str,
    body: CounselingNoteUpdate,
    user=Depends(get_current_teacher),
):
    """강사 개인 메모 저장/수정"""
    supabase = get_supabase()

    existing = (
        supabase.table("counseling_records")
        .select("id, counselor_id")
        .eq("id", record_id)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail="상담 기록을 찾을 수 없습니다.")
    if str(existing.data[0]["counselor_id"]) != str(user["id"]):
        raise HTTPException(status_code=403, detail="본인 기록만 수정할 수 있습니다.")

    supabase.table("counseling_records").update({"note": body.note}).eq(
        "id", record_id
    ).execute()

    return {"message": "메모가 저장되었습니다."}


# ═══════════════════════════════════════════════════
# 7. Q&A 답변
# ═══════════════════════════════════════════════════


@router.get("/questions", response_model=List[TeacherQuestionResponse])
async def list_teacher_questions(
    filter: Optional[str] = Query(None),
    user=Depends(get_current_teacher),
):
    """Q&A 목록 (전체/미답변/답변완료 필터) — 작성자의 수강 과정명 배지 포함."""
    supabase = get_supabase()

    query = (
        supabase.table("questions")
        .select("*, users(name, course_id)")
        .order("created_at", desc=True)
    )

    if filter == "unanswered":
        query = query.is_("answer", "null")
    elif filter == "answered":
        query = query.neq("answer", "null")

    res = query.execute()
    questions = res.data or []

    # course_id → course.name 맵
    course_ids = list({
        (q.get("users") or {}).get("course_id")
        for q in questions
        if isinstance(q.get("users"), dict) and (q.get("users") or {}).get("course_id")
    })
    course_name_map: dict = {}
    if course_ids:
        c_res = (
            supabase.table("courses")
            .select("id,name")
            .in_("id", course_ids)
            .execute()
        )
        course_name_map = {c["id"]: c["name"] for c in (c_res.data or [])}

    def _course_name_for(q):
        u = q.get("users") or {}
        if not isinstance(u, dict):
            return None
        return course_name_map.get(u.get("course_id"))

    return [
        TeacherQuestionResponse(
            id=str(q["id"]),
            user_id=str(q["user_id"]),
            content=q["content"],
            is_anonymous=q.get("is_anonymous", False),
            author=None if q.get("is_anonymous") else (q.get("users", {}) or {}).get("name"),
            course_name=_course_name_for(q),
            created_at=q.get("created_at", ""),
            answer=q.get("answer"),
            answered_at=q.get("answered_at"),
        )
        for q in questions
    ]


@router.patch("/questions/{question_id}")
async def answer_question(
    question_id: str, body: AnswerRequest, user=Depends(get_current_teacher)
):
    """질문에 답변 등록/수정"""
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


# ═══════════════════════════════════════════════════
# 헬퍼 함수
# ═══════════════════════════════════════════════════


def _get_teacher_course_ids(
    supabase, teacher_id: str, filter_course_id: Optional[str] = None
) -> List[str]:
    """강사의 담당 course_id 목록을 반환.

    - filter_course_id 미지정: 담당 과정 전체 반환
    - filter_course_id 지정 + 본인 담당: [filter_course_id]만 반환
    - filter_course_id 지정 + 담당 아님: 빈 배열 (쿼리가 조용히 빈 결과를 내도록)
    """
    tc = (
        supabase.table("teacher_courses")
        .select("course_id")
        .eq("teacher_id", teacher_id)
        .execute()
    )
    all_ids = [r["course_id"] for r in (tc.data or [])]
    if filter_course_id:
        return [filter_course_id] if filter_course_id in all_ids else []
    return all_ids


def _teacher_owns_course(supabase, teacher_id: str, course_id: Optional[str]) -> bool:
    """강사가 해당 course_id를 담당하는지 검사 (쓰기 API 권한 검증용)."""
    if not course_id:
        return False
    res = (
        supabase.table("teacher_courses")
        .select("course_id")
        .eq("teacher_id", teacher_id)
        .eq("course_id", course_id)
        .limit(1)
        .execute()
    )
    return bool(res.data)


def _get_teacher_students(
    supabase, teacher_id: str, filter_course_id: Optional[str] = None
) -> list:
    """강사가 담당하는 과정 학생 목록. filter_course_id로 단일 과정 한정 가능."""
    course_ids = _get_teacher_course_ids(supabase, teacher_id, filter_course_id)
    if not course_ids:
        return []
    res = (
        supabase.table("users")
        .select("id, name")
        .eq("role", "student")
        .in_("course_id", course_ids)
        .order("name")
        .execute()
    )
    return res.data or []


def _get_student_files(supabase, user_id: str) -> List[StudentFile]:
    """학생의 이력서/포트폴리오 파일 목록"""
    try:
        files_res = (
            supabase.table("student_files")
            .select("*")
            .eq("student_id", user_id)
            .execute()
        )
        return [
            StudentFile(
                name=f.get("name", ""),
                type=f.get("type", ""),
                url=f.get("url", ""),
                uploaded_at=f.get("uploaded_at", "")[:10] if f.get("uploaded_at") else None,
            )
            for f in (files_res.data or [])
        ]
    except Exception:
        return []
