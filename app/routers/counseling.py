from typing import List
from fastapi import APIRouter, HTTPException, Depends, Query
from app.dependencies import get_current_user
from app.utils.supabase_client import get_supabase
from app.schemas.counseling import (
    CounselorResponse,
    CounselingSlotResponse,
    CounselingBookRequest,
    CounselingBookingResponse,
)

router = APIRouter(prefix="/api/counseling", tags=["counseling"])

ROLE_LABEL_MAP = {
    "teacher": "강사",
    "admin": "멘토",
}

ALL_TIME_SLOTS = [
    "09:00", "09:30", "10:00", "10:30", "11:00", "11:30",
    "13:00", "13:30", "14:00", "14:30", "15:00", "15:30",
    "16:00", "16:30", "17:00",
]


@router.get("/counselors", response_model=List[CounselorResponse])
def list_counselors(user=Depends(get_current_user)):
    """상담사(강사/관리자) 목록 조회"""
    supabase = get_supabase()
    res = (
        supabase.table("users")
        .select("id, name, role")
        .in_("role", ["teacher", "admin"])
        .execute()
    )
    counselors = res.data or []

    return [
        CounselorResponse(
            id=str(c["id"]),
            name=c["name"],
            role=c.get("role"),
            role_label=ROLE_LABEL_MAP.get(c.get("role"), ""),
        )
        for c in counselors
    ]


@router.get("/slots/{counselor_id}", response_model=List[CounselingSlotResponse])
def get_counseling_slots(
    counselor_id: str,
    year: int = Query(None),
    month: int = Query(None),
    user=Depends(get_current_user),
):
    """상담사의 예약 가능 슬롯 조회 (날짜별) — blocked_slots + 기존 예약으로 가용 시간 계산"""
    from datetime import date

    supabase = get_supabase()
    today = date.today()
    year = year or today.year
    month = month or today.month

    start_date = f"{year}-{month:02d}-01"
    end_month = month + 1 if month < 12 else 1
    end_year = year if month < 12 else year + 1
    end_date = f"{end_year}-{end_month:02d}-01"

    # 차단 슬롯
    blocked_res = (
        supabase.table("counseling_blocked_slots")
        .select("date, time")
        .eq("counselor_id", counselor_id)
        .gte("date", start_date)
        .lt("date", end_date)
        .order("date")
        .order("time")
        .execute()
    )
    blocked_by_date: dict = {}
    for s in (blocked_res.data or []):
        d = s["date"]
        blocked_by_date.setdefault(d, set()).add(s["time"])

    # 이미 예약된 슬롯
    booked_res = (
        supabase.table("counseling_bookings")
        .select("date, time")
        .eq("counselor_id", counselor_id)
        .neq("status", "cancelled")
        .gte("date", start_date)
        .lt("date", end_date)
        .execute()
    )
    booked_by_date: dict = {}
    for b in (booked_res.data or []):
        d = b["date"]
        booked_by_date.setdefault(d, set()).add(b["time"][:5])  # HH:MM:SS → HH:MM

    # 날짜별 결과 생성
    import calendar
    num_days = calendar.monthrange(year, month)[1]
    result = []
    for day in range(1, num_days + 1):
        d = f"{year}-{month:02d}-{day:02d}"
        if d < today.isoformat():
            continue
        blocked = blocked_by_date.get(d, set())
        booked = booked_by_date.get(d, set())
        unavailable = blocked | booked
        available = [t for t in ALL_TIME_SLOTS if t not in unavailable]
        if available or blocked:
            result.append(CounselingSlotResponse(
                date=d,
                available_times=available,
                blocked_times=sorted(blocked),
            ))

    return result


@router.post("/book", response_model=CounselingBookingResponse)
def book_counseling(body: CounselingBookRequest, user=Depends(get_current_user)):
    """상담 예약"""
    supabase = get_supabase()

    # 차단 슬롯 확인
    blocked = (
        supabase.table("counseling_blocked_slots")
        .select("id")
        .eq("counselor_id", body.counselor_id)
        .eq("date", body.date)
        .eq("time", body.time)
        .execute()
    )
    if blocked.data:
        raise HTTPException(status_code=409, detail="해당 시간은 상담 불가 시간입니다.")

    # 이미 예약된 시간 확인
    existing = (
        supabase.table("counseling_bookings")
        .select("id")
        .eq("counselor_id", body.counselor_id)
        .eq("date", body.date)
        .eq("time", body.time)
        .neq("status", "cancelled")
        .execute()
    )
    if existing.data:
        raise HTTPException(status_code=409, detail="이미 예약된 시간입니다.")

    # 중복 예약 방지 (본인)
    dup_res = (
        supabase.table("counseling_bookings")
        .select("id")
        .eq("student_id", user["id"])
        .eq("counselor_id", body.counselor_id)
        .eq("date", body.date)
        .eq("time", body.time)
        .neq("status", "cancelled")
        .execute()
    )
    if dup_res.data:
        raise HTTPException(status_code=409, detail="이미 동일한 시간에 예약이 있습니다.")

    # 상담사 정보 조회
    counselor_res = (
        supabase.table("users")
        .select("name, role")
        .eq("id", body.counselor_id)
        .execute()
    )
    counselor = counselor_res.data[0] if counselor_res.data else {}

    # 학생 이름 조회
    student_res = (
        supabase.table("users")
        .select("name")
        .eq("id", user["id"])
        .execute()
    )
    student_name = student_res.data[0]["name"] if student_res.data else ""

    # 예약 생성
    booking_res = (
        supabase.table("counseling_bookings")
        .insert(
            {
                "counselor_id": body.counselor_id,
                "counselor_name": counselor.get("name"),
                "counselor_role": counselor.get("role"),
                "counselor_role_label": ROLE_LABEL_MAP.get(counselor.get("role"), ""),
                "student_id": user["id"],
                "student_name": student_name,
                "date": body.date,
                "time": body.time,
                "reason": body.reason,
                "status": "pending",
            }
        )
        .execute()
    )

    b = booking_res.data[0]
    return CounselingBookingResponse(
        id=str(b["id"]),
        counselor_id=str(b["counselor_id"]),
        counselor_name=b.get("counselor_name"),
        counselor_role=b.get("counselor_role"),
        counselor_role_label=b.get("counselor_role_label"),
        student_id=str(b.get("student_id", "")),
        student_name=b.get("student_name"),
        date=b["date"],
        time=b["time"][:5],  # HH:MM:SS → HH:MM
        reason=b.get("reason"),
        status=b["status"],
    )


@router.get("/bookings", response_model=List[CounselingBookingResponse])
def my_bookings(user=Depends(get_current_user)):
    """내 상담 예약 목록"""
    supabase = get_supabase()

    res = (
        supabase.table("counseling_bookings")
        .select("*")
        .eq("student_id", user["id"])
        .order("date", desc=True)
        .execute()
    )
    bookings = res.data or []

    return [
        CounselingBookingResponse(
            id=str(b["id"]),
            counselor_id=str(b["counselor_id"]),
            counselor_name=b.get("counselor_name"),
            counselor_role=b.get("counselor_role"),
            counselor_role_label=b.get("counselor_role_label"),
            student_id=str(b.get("student_id", "")),
            student_name=b.get("student_name"),
            date=b["date"],
            time=b["time"][:5],  # HH:MM:SS → HH:MM
            reason=b.get("reason"),
            status=b["status"],
        )
        for b in bookings
    ]


@router.delete("/bookings/{booking_id}")
def cancel_booking(booking_id: str, user=Depends(get_current_user)):
    """상담 예약 취소"""
    supabase = get_supabase()

    res = (
        supabase.table("counseling_bookings")
        .select("id, student_id, status")
        .eq("id", booking_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="예약을 찾을 수 없습니다.")

    booking = res.data[0] if isinstance(res.data, list) else res.data
    if booking.get("student_id") != user["id"]:
        raise HTTPException(status_code=403, detail="본인의 예약만 취소할 수 있습니다.")
    if booking.get("status") == "cancelled":
        raise HTTPException(status_code=409, detail="이미 취소된 예약입니다.")

    supabase.table("counseling_bookings").update({"status": "cancelled"}).eq(
        "id", booking_id
    ).execute()

    return {"message": "상담 예약이 취소되었습니다."}

