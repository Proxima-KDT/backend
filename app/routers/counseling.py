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


@router.get("/counselors", response_model=List[CounselorResponse])
def list_counselors(user=Depends(get_current_user)):
    """상담사 목록 조회"""
    supabase = get_supabase()
    res = supabase.table("counselors").select("*").eq("is_active", True).execute()
    counselors = res.data or []

    return [
        CounselorResponse(
            id=str(c["id"]),
            name=c["name"],
            role=c.get("role"),
            role_label=c.get("role_label"),
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
    """상담사의 예약 가능 슬롯 조회 (날짜별)"""
    from datetime import date

    supabase = get_supabase()
    today = date.today()
    year = year or today.year
    month = month or today.month

    start_date = f"{year}-{month:02d}-01"
    end_month = month + 1 if month < 12 else 1
    end_year = year if month < 12 else year + 1
    end_date = f"{end_year}-{end_month:02d}-01"

    slots_res = (
        supabase.table("counseling_slots")
        .select("date, time_slot, is_available")
        .eq("counselor_id", counselor_id)
        .eq("is_available", True)
        .gte("date", start_date)
        .lt("date", end_date)
        .order("date")
        .order("time_slot")
        .execute()
    )
    slots = slots_res.data or []

    # 날짜별 그룹핑
    slots_by_date: dict = {}
    for slot in slots:
        d = slot["date"]
        slots_by_date.setdefault(d, []).append(slot["time_slot"])

    return [
        CounselingSlotResponse(date=d, times=times) for d, times in slots_by_date.items()
    ]


@router.post("/book", response_model=CounselingBookingResponse)
def book_counseling(body: CounselingBookRequest, user=Depends(get_current_user)):
    """상담 예약"""
    supabase = get_supabase()

    # 슬롯 유효성 확인
    slot_res = (
        supabase.table("counseling_slots")
        .select("id, is_available")
        .eq("counselor_id", body.counselor_id)
        .eq("date", body.date)
        .eq("time_slot", body.time)
        .execute()
    )
    if not slot_res.data or not slot_res.data.get("is_available"):
        raise HTTPException(status_code=409, detail="이미 예약된 시간이거나 예약 불가능한 슬롯입니다.")

    # 중복 예약 방지
    dup_res = (
        supabase.table("counseling_bookings")
        .select("id")
        .eq("user_id", user["id"])
        .eq("counselor_id", body.counselor_id)
        .eq("date", body.date)
        .eq("time", body.time)
        .neq("status", "cancelled")
        .execute()
    )
    if dup_res.data:
        raise HTTPException(status_code=409, detail="이미 동일한 시간에 예약이 있습니다.")

    # 예약 생성
    booking_res = (
        supabase.table("counseling_bookings")
        .insert(
            {
                "user_id": user["id"],
                "counselor_id": body.counselor_id,
                "date": body.date,
                "time": body.time,
                "reason": body.reason,
                "status": "pending",
            }
        )
        .execute()
    )

    # 슬롯 비가용으로 표시
    supabase.table("counseling_slots").update({"is_available": False}).eq(
        "id", slot_res.data["id"]
    ).execute()

    # 상담사 정보 조회
    counselor_res = (
        supabase.table("counselors")
        .select("name, role_label")
        .eq("id", body.counselor_id)
        .execute()
    )
    counselor_data = counselor_res.data or {}

    b = booking_res.data[0]
    return CounselingBookingResponse(
        id=str(b["id"]),
        counselor_id=str(b["counselor_id"]),
        counselor_name=counselor_data.get("name"),
        counselor_role_label=counselor_data.get("role_label"),
        date=b["date"],
        time=b["time"],
        reason=b.get("reason"),
        status=b["status"],
    )


@router.get("/bookings", response_model=List[CounselingBookingResponse])
def my_bookings(user=Depends(get_current_user)):
    """내 상담 예약 목록"""
    supabase = get_supabase()

    res = (
        supabase.table("counseling_bookings")
        .select("*, counselors(name, role_label)")
        .eq("user_id", user["id"])
        .order("date", desc=True)
        .execute()
    )
    bookings = res.data or []

    return [
        CounselingBookingResponse(
            id=str(b["id"]),
            counselor_id=str(b["counselor_id"]),
            counselor_name=b.get("counselors", {}).get("name") if b.get("counselors") else None,
            counselor_role_label=(
                b.get("counselors", {}).get("role_label") if b.get("counselors") else None
            ),
            date=b["date"],
            time=b["time"],
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
        .select("id, user_id, counselor_id, date, time, status")
        .eq("id", booking_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="예약을 찾을 수 없습니다.")
    if res.data.get("user_id") != user["id"]:
        raise HTTPException(status_code=403, detail="본인의 예약만 취소할 수 있습니다.")
    if res.data.get("status") == "cancelled":
        raise HTTPException(status_code=409, detail="이미 취소된 예약입니다.")

    supabase.table("counseling_bookings").update({"status": "cancelled"}).eq(
        "id", booking_id
    ).execute()

    # 슬롯 다시 가용으로 변경
    supabase.table("counseling_slots").update({"is_available": True}).eq(
        "counselor_id", res.data["counselor_id"]
    ).eq("date", res.data["date"]).eq("time_slot", res.data["time"]).execute()

    return {"message": "상담 예약이 취소되었습니다."}

