from datetime import date, datetime, timedelta
from typing import List, Optional
import uuid
from fastapi import APIRouter, HTTPException, Depends, Query
from app.dependencies import get_current_admin
from app.utils.supabase_client import get_supabase
from app.schemas.admin import (
    AdminStudentResponse,
    UserRoleUpdateRequest,
    CreateStudentRequest,
    CreateTeacherRequest,
    CreateUserResponse,
    UpdateUserPasswordRequest,
    CourseResponse,
    AdminEquipmentResponse,
    EquipmentCreateRequest,
    EquipmentStatusUpdate,
    EquipmentRequestResponse,
    EquipmentRejectRequest,
    EquipmentHistoryItem,
    EquipmentSession,
    AdminRoomResponse,
    RoomCreateRequest,
    RoomUpdateRequest,
    RoomStatusUpdate,
    AdminBookedSlotResponse,
)
from app.services import admin_users_service

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ═══════════════════════════════════════════════════
# 1. 대시보드 & 학생 관리
# ═══════════════════════════════════════════════════


@router.get("/students", response_model=List[AdminStudentResponse])
def list_admin_students(
    search: Optional[str] = Query(None),
    user=Depends(get_current_admin),
):
    """관리자 학생 목록 (검색 지원) — N+1 방지: 배치 쿼리"""
    supabase = get_supabase()

    query = supabase.table("users").select("*").eq("role", "student").order("name")
    if search:
        query = query.or_(f"name.ilike.%{search}%,email.ilike.%{search}%")
    profiles_res = query.execute()
    students = profiles_res.data or []

    if not students:
        return []

    student_ids = [s["id"] for s in students]

    # 스킬 동적 계산 (teacher와 동일 로직)
    from app.services.skill_service import calculate_students_skills_batch
    skills_by_user = calculate_students_skills_batch(supabase, student_ids)

    files_res = (
        supabase.table("student_files")
        .select("student_id, name, type, url, uploaded_at")
        .in_("student_id", student_ids)
        .execute()
    )

    files_by_user: dict = {}
    for f in (files_res.data or []):
        files_by_user.setdefault(f["student_id"], []).append({
            "name": f.get("name", ""),
            "type": f.get("type", ""),
            "url": f.get("url", ""),
            "uploaded_at": f.get("uploaded_at", "")[:10] if f.get("uploaded_at") else None,
        })

    # 과정/기수 매핑
    course_ids = list({s["course_id"] for s in students if s.get("course_id")})
    cohort_ids = list({s["cohort_id"] for s in students if s.get("cohort_id")})
    course_map: dict = {}
    if course_ids:
        cr = supabase.table("courses").select("id,name").in_("id", course_ids).execute()
        course_map = {c["id"]: c["name"] for c in (cr.data or [])}
    cohort_map: dict = {}
    if cohort_ids:
        coh = supabase.table("cohorts").select("id,cohort_number").in_("id", cohort_ids).execute()
        cohort_map = {c["id"]: c["cohort_number"] for c in (coh.data or [])}

    result = []
    for s in students:
        uid = s["id"]
        att_rate = float(skills_by_user.get(uid, {}).get("출결", 0))

        result.append(
            AdminStudentResponse(
                id=uid,
                name=s.get("name", ""),
                email=s.get("email"),
                avatar_url=s.get("avatar_url"),
                role=s.get("role", "student"),
                attendance_rate=att_rate,
                submission_rate=0,
                is_at_risk=att_rate < 80,
                last_active=s.get("updated_at", "")[:10] if s.get("updated_at") else None,
                enrolled_at=s.get("created_at", "")[:10] if s.get("created_at") else None,
                skills=skills_by_user.get(uid, {}),
                files=files_by_user.get(uid, []),
                address=s.get("address"),
                phone=s.get("phone"),
                course_id=s.get("course_id"),
                course_name=course_map.get(s.get("course_id")),
                cohort_id=s.get("cohort_id"),
                cohort_number=cohort_map.get(s.get("cohort_id")),
            )
        )
    return result


@router.get("/students/{student_id}", response_model=AdminStudentResponse)
def get_admin_student_detail(student_id: str, user=Depends(get_current_admin)):
    """학생 상세 정보 (관리자)"""
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

    # 스킬 동적 계산 (teacher와 동일 로직)
    from app.services.skill_service import calculate_student_skills
    skills = calculate_student_skills(supabase, uid)
    att_rate = float(skills.get("출결", 0))

    files = _get_student_files(supabase, uid)

    # 과정/기수 정보
    course_name = None
    cohort_number = None
    if s.get("course_id"):
        cr = supabase.table("courses").select("name").eq("id", s["course_id"]).limit(1).execute()
        if cr.data:
            course_name = cr.data[0]["name"]
    if s.get("cohort_id"):
        coh = supabase.table("cohorts").select("cohort_number").eq("id", s["cohort_id"]).limit(1).execute()
        if coh.data:
            cohort_number = coh.data[0]["cohort_number"]

    return AdminStudentResponse(
        id=uid,
        name=s.get("name", ""),
        email=s.get("email"),
        avatar_url=s.get("avatar_url"),
        role=s.get("role", "student"),
        attendance_rate=att_rate,
        submission_rate=0,
        is_at_risk=att_rate < 80,
        last_active=s.get("updated_at", "")[:10] if s.get("updated_at") else None,
        enrolled_at=s.get("created_at", "")[:10] if s.get("created_at") else None,
        skills=skills,
        files=files,
        address=s.get("address"),
        phone=s.get("phone"),
        course_id=s.get("course_id"),
        course_name=course_name,
        cohort_id=s.get("cohort_id"),
        cohort_number=cohort_number,
    )


@router.get("/students/{student_id}/attendance/week")
def get_admin_student_weekly_attendance(
    student_id: str,
    date_str: str = Query(None, alias="date"),
    user=Depends(get_current_admin),
):
    """학생 주간 출결 (관리자)"""
    supabase = get_supabase()

    base_date = date.fromisoformat(date_str) if date_str else date.today()
    monday = base_date - timedelta(days=base_date.weekday())

    res = (
        supabase.table("attendance")
        .select("date, status, check_in_time")
        .eq("user_id", student_id)
        .gte("date", monday.isoformat())
        .lte("date", (monday + timedelta(days=6)).isoformat())
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


@router.put("/students/{student_id}/notes")
def save_admin_student_notes(
    student_id: str,
    body: dict,
    user=Depends(get_current_admin),
):
    """학생 상담 메모 저장 (관리자) — counseling_records에 저장"""
    supabase = get_supabase()
    notes = body.get("notes", "")

    # 학생 이름 조회
    student_res = supabase.table("users").select("name").eq("id", student_id).execute()
    student_name = student_res.data[0]["name"] if student_res.data else ""

    supabase.table("counseling_records").insert({
        "student_id": student_id,
        "student_name": student_name,
        "counselor_id": user["id"],
        "date": date.today().isoformat(),
        "summary": notes,
    }).execute()

    return {"message": "상담 메모가 저장되었습니다."}


@router.get("/students/{student_id}/files")
def get_admin_student_files(student_id: str, user=Depends(get_current_admin)):
    """학생 파일 목록 (이력서/포트폴리오)"""
    supabase = get_supabase()
    files = _get_student_files(supabase, student_id)
    return files


# ═══════════════════════════════════════════════════
# 2. 사용자 관리
# ═══════════════════════════════════════════════════


@router.get("/users")
def list_admin_users(
    search: Optional[str] = Query(None),
    user=Depends(get_current_admin),
):
    """전체 사용자 목록 (검색 지원)"""
    supabase = get_supabase()

    query = supabase.table("users").select("*").order("name")

    if search:
        query = query.or_(f"name.ilike.%{search}%,email.ilike.%{search}%")

    res = query.execute()
    users = res.data or []

    return [
        {
            "id": u["id"],
            "name": u.get("name", ""),
            "email": u.get("email"),
            "role": u.get("role", "student"),
            "avatar_url": u.get("avatar_url"),
            "enrolled_at": u.get("created_at", "")[:10] if u.get("created_at") else None,
        }
        for u in users
    ]


@router.put("/users/{user_id}/role")
def update_user_role(
    user_id: str, body: UserRoleUpdateRequest, user=Depends(get_current_admin)
):
    """사용자 역할 변경"""
    supabase = get_supabase()

    if body.new_role not in ("student", "teacher", "admin"):
        raise HTTPException(status_code=400, detail="유효하지 않은 역할입니다.")

    existing = (
        supabase.table("users")
        .select("id")
        .eq("id", user_id)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    supabase.table("users").update(
        {"role": body.new_role}
    ).eq("id", user_id).execute()

    return {"message": f"역할이 {body.new_role}(으)로 변경되었습니다."}


# ═══════════════════════════════════════════════════
# 3. 장비 관리
# ═══════════════════════════════════════════════════


@router.get("/equipment", response_model=List[AdminEquipmentResponse])
def list_admin_equipment(
    category: Optional[str] = Query(None),
    user=Depends(get_current_admin),
):
    """장비 전체 목록"""
    supabase = get_supabase()

    query = supabase.table("equipment").select("*").order("category").order("name")
    if category:
        query = query.eq("category", category)

    res = query.execute()
    items = res.data or []

    return [
        AdminEquipmentResponse(
            id=str(item["id"]),
            name=item["name"],
            serial_no=item["serial_no"],
            category=item.get("category"),
            status=item["status"],
            borrower=item.get("borrower_name"),
            borrower_id=str(item["borrower_id"]) if item.get("borrower_id") else None,
            borrowed_at=item.get("borrowed_at"),
        )
        for item in items
    ]


@router.get("/equipment/{equipment_id}/history", response_model=List[EquipmentSession])
def get_equipment_history(equipment_id: str, user=Depends(get_current_admin)):
    """장비 사용 이력 — borrow/return 쌍을 세션으로 묶어 반환"""
    supabase = get_supabase()

    res = (
        supabase.table("equipment_logs")
        .select("*, users!equipment_logs_user_id_fkey(name)")
        .eq("equipment_id", equipment_id)
        .order("created_at", desc=False)  # 오래된 순 정렬 후 페어링
        .execute()
    )
    logs = res.data or []

    def get_name(log):
        u = log.get("users")
        return u.get("name") if isinstance(u, dict) else None

    sessions: list = []
    # user_id 기준 미반납 대여 로그 임시 저장
    pending: dict = {}  # user_id -> log

    for log in logs:
        action = log.get("action")
        uid = log.get("user_id")
        ts = log.get("created_at", "")

        if action == "borrow":
            # 같은 사용자의 이전 미반납 대여가 있으면 우선 is_active=True로 추가
            if uid in pending:
                prev = pending.pop(uid)
                sessions.append(EquipmentSession(
                    user_name=get_name(prev),
                    borrow_at=prev.get("created_at"),
                    return_at=None,
                    is_active=True,
                    note=prev.get("note"),
                    action="borrow",
                ))
            pending[uid] = log

        elif action == "return":
            borrow_log = pending.pop(uid, None)
            sessions.append(EquipmentSession(
                user_name=get_name(log) or (get_name(borrow_log) if borrow_log else None),
                borrow_at=borrow_log.get("created_at") if borrow_log else None,
                return_at=ts,
                is_active=False,
                note=log.get("note"),
                action="borrow",
            ))

        else:
            # maintenance / status_change 등 기타 이벤트
            sessions.append(EquipmentSession(
                user_name=get_name(log),
                borrow_at=ts,
                return_at=None,
                is_active=False,
                note=log.get("note"),
                action=action or "status_change",
            ))

    # 아직 반납 안 된 pending 대여
    for pending_log in pending.values():
        sessions.append(EquipmentSession(
            user_name=get_name(pending_log),
            borrow_at=pending_log.get("created_at"),
            return_at=None,
            is_active=True,
            note=pending_log.get("note"),
            action="borrow",
        ))

    # 최신 순 정렬 (borrow_at 기준, 없으면 return_at)
    sessions.sort(
        key=lambda s: s.borrow_at or s.return_at or "",
        reverse=True,
    )
    return sessions


@router.post("/equipment", response_model=AdminEquipmentResponse)
def create_equipment(body: EquipmentCreateRequest, user=Depends(get_current_admin)):
    """장비 등록 — 시리얼 중복 방지"""
    supabase = get_supabase()

    # 시리얼 중복 체크
    dup = (
        supabase.table("equipment")
        .select("id, name")
        .eq("serial_no", body.serial_no)
        .execute()
    )
    if dup.data:
        existing_name = dup.data[0].get("name", "")
        raise HTTPException(
            status_code=409,
            detail=f"시리얼 '{body.serial_no}'은(는) 이미 등록된 장비입니다. ({existing_name})",
        )

    res = (
        supabase.table("equipment")
        .insert({
            "name": body.name,
            "serial_no": body.serial_no,
            "category": body.category,
            "status": "available",
        })
        .execute()
    )
    item = res.data[0]
    return AdminEquipmentResponse(
        id=str(item["id"]),
        name=item["name"],
        serial_no=item["serial_no"],
        category=item.get("category"),
        status=item["status"],
        borrower=item.get("borrower_name"),
        borrower_id=str(item["borrower_id"]) if item.get("borrower_id") else None,
        borrowed_at=item.get("borrowed_at"),
    )


@router.get("/equipment/requests", response_model=List[EquipmentRequestResponse])
def list_equipment_requests(
    status: Optional[str] = Query("pending"),
    user=Depends(get_current_admin),
):
    """장비 대여 요청 목록"""
    supabase = get_supabase()

    query = (
        supabase.table("equipment_requests")
        .select("*")
        .order("created_at", desc=True)
    )
    if status and status != "all":
        query = query.eq("status", status)

    res = query.execute()
    requests = res.data or []

    return [
        EquipmentRequestResponse(
            id=str(r["id"]),
            student_name=r.get("student_name"),
            equipment_name=r.get("equipment_name"),
            request_date=r.get("created_at", "")[:10] if r.get("created_at") else None,
            reason=r.get("reason"),
            status=r.get("status", "pending"),
        )
        for r in requests
    ]


@router.post("/equipment/requests/{request_id}/approve")
def approve_equipment_request(request_id: str, user=Depends(get_current_admin)):
    """장비 대여 승인"""
    supabase = get_supabase()

    req_res = (
        supabase.table("equipment_requests")
        .select("id, equipment_id, user_id, status")
        .eq("id", request_id)
        .execute()
    )
    if not req_res.data:
        raise HTTPException(status_code=404, detail="요청을 찾을 수 없습니다.")

    req = req_res.data[0] if isinstance(req_res.data, list) else req_res.data
    if req["status"] != "pending":
        raise HTTPException(status_code=409, detail="이미 처리된 요청입니다.")

    equipment_id = req["equipment_id"]

    # 사용자 이름 가져오기
    user_res = (
        supabase.table("users")
        .select("name")
        .eq("id", req["user_id"])
        .execute()
    )
    borrower_name = user_res.data[0]["name"] if user_res.data else ""

    # 요청 승인
    supabase.table("equipment_requests").update(
        {"status": "approved", "decided_by": user["id"]}
    ).eq("id", request_id).execute()

    from datetime import datetime
    now_iso = datetime.utcnow().isoformat() + "+00:00"

    # 장비 상태 업데이트
    supabase.table("equipment").update({
        "status": "borrowed",
        "borrower_id": req["user_id"],
        "borrower_name": borrower_name,
        "borrowed_at": date.today().isoformat(),
    }).eq("id", equipment_id).execute()

    # 대여 로그 기록 — 이 로그가 있어야 이력에서 대여 시각을 표시할 수 있음
    supabase.table("equipment_logs").insert({
        "equipment_id": equipment_id,
        "user_id": req["user_id"],
        "action": "borrow",
        "created_at": now_iso,
    }).execute()

    return {"message": "대여 요청이 승인되었습니다."}


@router.post("/equipment/requests/{request_id}/reject")
def reject_equipment_request(
    request_id: str, body: EquipmentRejectRequest, user=Depends(get_current_admin)
):
    """장비 대여 반려"""
    supabase = get_supabase()

    req_res = (
        supabase.table("equipment_requests")
        .select("id, status")
        .eq("id", request_id)
        .execute()
    )
    if not req_res.data:
        raise HTTPException(status_code=404, detail="요청을 찾을 수 없습니다.")

    req = req_res.data[0] if isinstance(req_res.data, list) else req_res.data
    if req["status"] != "pending":
        raise HTTPException(status_code=409, detail="이미 처리된 요청입니다.")

    supabase.table("equipment_requests").update({
        "status": "rejected",
        "reject_reason": body.reason,
        "decided_by": user["id"],
    }).eq("id", request_id).execute()

    return {"message": "대여 요청이 반려되었습니다."}


@router.put("/equipment/{equipment_id}/status")
def update_equipment_status(
    equipment_id: str, body: EquipmentStatusUpdate, user=Depends(get_current_admin)
):
    """장비 상태 변경"""
    supabase = get_supabase()

    existing = (
        supabase.table("equipment")
        .select("id")
        .eq("id", equipment_id)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail="장비를 찾을 수 없습니다.")

    update_data = {"status": body.status}
    # 사용 가능으로 변경 시 대여자 정보 초기화
    if body.status == "available":
        update_data["borrower_id"] = None
        update_data["borrower_name"] = None
        update_data["borrowed_at"] = None

    supabase.table("equipment").update(update_data).eq("id", equipment_id).execute()

    return {"message": f"장비 상태가 {body.status}(으)로 변경되었습니다."}


# ═══════════════════════════════════════════════════
# 4. 시설 예약 관리
# ═══════════════════════════════════════════════════


@router.get("/rooms", response_model=List[AdminRoomResponse])
def list_admin_rooms(user=Depends(get_current_admin)):
    """방 목록 (관리자)"""
    supabase = get_supabase()

    res = supabase.table("rooms").select("*").order("name").execute()
    rooms = res.data or []

    return [
        AdminRoomResponse(
            id=str(r["id"]),
            name=r["name"],
            type=r.get("type", "study"),
            capacity=r.get("capacity", 0),
            floor=r.get("floor"),
            amenities=r.get("amenities") or [],
            status=r.get("status", "open"),
        )
        for r in rooms
    ]


@router.get("/rooms/slots", response_model=List[AdminBookedSlotResponse])
def get_admin_room_slots(
    date_str: str = Query(..., alias="date"),
    user=Depends(get_current_admin),
):
    """특정 날짜의 전체 예약 현황"""
    supabase = get_supabase()

    res = (
        supabase.table("room_reservations")
        .select("*, users!room_reservations_user_id_fkey(name)")
        .eq("date", date_str)
        .neq("status", "cancelled")
        .order("start_time")
        .execute()
    )
    slots = res.data or []

    return [
        AdminBookedSlotResponse(
            id=str(s["id"]),
            room_id=str(s["room_id"]),
            date=s["date"],
            start_time=s["start_time"],
            end_time=s["end_time"],
            reserved_by=(s.get("users") or {}).get("name") if isinstance(s.get("users"), dict) else None,
            purpose=s.get("purpose"),
            user_id=str(s.get("user_id", "")),
        )
        for s in slots
    ]


@router.post("/rooms")
def create_room(body: RoomCreateRequest, user=Depends(get_current_admin)):
    """방 등록"""
    supabase = get_supabase()

    # varchar(20) 제한: "room-" + 8자 hex = 13자
    new_id = f"room-{uuid.uuid4().hex[:8]}"
    res = (
        supabase.table("rooms")
        .insert({
            "id": new_id,
            "name": body.name,
            "type": body.type,
            "capacity": body.capacity,
            "floor": body.floor,
            "amenities": body.amenities,
            "status": "open",
        })
        .execute()
    )
    return {"message": "방이 등록되었습니다.", "id": str(res.data[0]["id"])}


@router.put("/rooms/{room_id}")
def update_room(room_id: str, body: RoomUpdateRequest, user=Depends(get_current_admin)):
    """방 정보 수정"""
    supabase = get_supabase()

    existing = (
        supabase.table("rooms")
        .select("id")
        .eq("id", room_id)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail="방을 찾을 수 없습니다.")

    update_data = {}
    if body.name is not None:
        update_data["name"] = body.name
    if body.type is not None:
        update_data["type"] = body.type
    if body.capacity is not None:
        update_data["capacity"] = body.capacity
    if body.floor is not None:
        update_data["floor"] = body.floor
    if body.amenities is not None:
        update_data["amenities"] = body.amenities

    if update_data:
        supabase.table("rooms").update(update_data).eq("id", room_id).execute()

    return {"message": "방 정보가 수정되었습니다."}


@router.put("/rooms/{room_id}/status")
def update_room_status(
    room_id: str, body: RoomStatusUpdate, user=Depends(get_current_admin)
):
    """방 운영 상태 변경 (open/closed)"""
    supabase = get_supabase()

    existing = (
        supabase.table("rooms")
        .select("id")
        .eq("id", room_id)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail="방을 찾을 수 없습니다.")

    supabase.table("rooms").update(
        {"status": body.status}
    ).eq("id", room_id).execute()

    status_label = "운영 재개" if body.status == "open" else "운영 중단"
    return {"message": f"방이 {status_label}되었습니다."}


@router.delete("/rooms/reservations/{reservation_id}")
def force_cancel_reservation(reservation_id: str, user=Depends(get_current_admin)):
    """예약 강제 취소 (관리자)"""
    supabase = get_supabase()

    existing = (
        supabase.table("room_reservations")
        .select("id, status")
        .eq("id", reservation_id)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail="예약을 찾을 수 없습니다.")
    if existing.data.get("status") == "cancelled":
        raise HTTPException(status_code=409, detail="이미 취소된 예약입니다.")

    supabase.table("room_reservations").update(
        {"status": "cancelled"}
    ).eq("id", reservation_id).execute()

    return {"message": "예약이 강제 취소되었습니다."}


# ═══════════════════════════════════════════════════
# 헬퍼 함수
# ═══════════════════════════════════════════════════


def _get_student_files(supabase, student_id: str) -> list:
    """학생 파일 목록 조회"""
    try:
        files_res = (
            supabase.table("student_files")
            .select("*")
            .eq("student_id", student_id)
            .execute()
        )
        return [
            {
                "name": f.get("name", ""),
                "type": f.get("type", ""),
                "url": f.get("url", ""),
                "uploaded_at": f.get("uploaded_at", "")[:10] if f.get("uploaded_at") else None,
            }
            for f in (files_res.data or [])
        ]
    except Exception:
        return []


# ═══════════════════════════════════════════════════
# 9. 계정 관리 — 관리자가 학생/강사 계정 생성
# ═══════════════════════════════════════════════════


@router.get("/courses", response_model=List[CourseResponse])
def list_admin_courses(_admin=Depends(get_current_admin)):
    """과정(course) 목록 + 각 과정의 기수(cohorts) 포함."""
    return admin_users_service.list_courses()


@router.post(
    "/users/students",
    response_model=CreateUserResponse,
    status_code=201,
)
def admin_create_student(
    payload: CreateStudentRequest,
    _admin=Depends(get_current_admin),
):
    """관리자 전용 — 학생 계정 생성 (과정 + 기수 연결)"""
    return admin_users_service.create_student(
        email=payload.email,
        password=payload.password,
        name=payload.name,
        address=payload.address,
        phone=payload.phone,
        course_id=payload.course_id,
        cohort_id=payload.cohort_id,
    )


@router.post(
    "/users/teachers",
    response_model=CreateUserResponse,
    status_code=201,
)
def admin_create_teacher(
    payload: CreateTeacherRequest,
    _admin=Depends(get_current_admin),
):
    """관리자 전용 — 강사 계정 생성 (여러 과정 담당 가능)"""
    return admin_users_service.create_teacher(
        email=payload.email,
        password=payload.password,
        name=payload.name,
        address=payload.address,
        phone=payload.phone,
        course_ids=payload.course_ids,
    )


@router.post("/users/{user_id}/password")
def admin_reset_user_password(
    user_id: str,
    payload: UpdateUserPasswordRequest,
    _admin=Depends(get_current_admin),
):
    """관리자 전용 — 사용자 비밀번호 재발급"""
    admin_users_service.update_user_password(user_id, payload.new_password)
    return {"message": "비밀번호가 변경되었습니다."}
