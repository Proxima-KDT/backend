from typing import List, Optional, Dict
from fastapi import APIRouter, HTTPException, Depends, Query
from app.dependencies import get_teacher_or_admin
from app.utils.supabase_client import get_supabase
from app.schemas.counseling_manage import (
    CounselingBookingResponse,
    BookingActionRequest,
    BlockedSlotsUpdate,
)

router = APIRouter(prefix="/api/counseling/manage", tags=["counseling-manage"])


@router.get("/schedule")
def get_counseling_schedule(
    month: Optional[str] = Query(None, description="YYYY-MM"),
    user=Depends(get_teacher_or_admin),
):
    """월간 상담 스케줄 (예약 + 차단 슬롯) — 강사/관리자 공용"""
    from datetime import date as date_type

    supabase = get_supabase()

    if month:
        year, mon = month.split("-")
        year, mon = int(year), int(mon)
    else:
        today = date_type.today()
        year, mon = today.year, today.month

    start_date = f"{year}-{mon:02d}-01"
    end_mon = mon + 1 if mon < 12 else 1
    end_year = year if mon < 12 else year + 1
    end_date = f"{end_year}-{end_mon:02d}-01"

    # 예약 목록 (counseling_bookings에 student_name 직접 저장됨)
    bookings_res = (
        supabase.table("counseling_bookings")
        .select("*")
        .gte("date", start_date)
        .lt("date", end_date)
        .order("date")
        .order("time")
        .execute()
    )
    bookings = []
    for b in (bookings_res.data or []):
        bookings.append({
            "id": str(b["id"]),
            "student_id": str(b.get("student_id", "")),
            "student_name": b.get("student_name"),
            "counselor_id": str(b.get("counselor_id", "")),
            "counselor_name": b.get("counselor_name"),
            "date": b["date"],
            "time": b.get("time", ""),
            "duration": b.get("duration", 30),
            "reason": b.get("reason"),
            "status": b.get("status", "pending"),
        })

    # 차단 슬롯 (counseling_blocked_slots)
    blocked_res = (
        supabase.table("counseling_blocked_slots")
        .select("counselor_id, date, time")
        .gte("date", start_date)
        .lt("date", end_date)
        .execute()
    )
    blocked_slots: Dict[str, List[str]] = {}
    for slot in (blocked_res.data or []):
        d = slot["date"]
        blocked_slots.setdefault(d, []).append(slot["time"])

    return {
        "bookings": bookings,
        "blocked_slots": blocked_slots,
    }


@router.patch("/blocked-slots/{date_str}")
def update_blocked_slots(
    date_str: str,
    body: BlockedSlotsUpdate,
    user=Depends(get_teacher_or_admin),
):
    """특정 날짜의 차단 슬롯 업데이트 (전체 교체 방식)"""
    supabase = get_supabase()

    # 기존 차단 슬롯 가져오기
    existing_res = (
        supabase.table("counseling_blocked_slots")
        .select("id, time")
        .eq("counselor_id", user["id"])
        .eq("date", date_str)
        .execute()
    )
    existing_map = {s["time"]: s for s in (existing_res.data or [])}

    # 새로 차단할 시간 추가
    for time_slot in body.blocked_times:
        if time_slot not in existing_map:
            supabase.table("counseling_blocked_slots").insert({
                "counselor_id": user["id"],
                "date": date_str,
                "time": time_slot,
            }).execute()

    # 차단 해제: 기존에 있었지만 새 목록에 없는 슬롯 → 삭제
    for time_slot, slot_data in existing_map.items():
        if time_slot not in body.blocked_times:
            supabase.table("counseling_blocked_slots").delete().eq(
                "id", slot_data["id"]
            ).execute()

    return {"message": "차단 슬롯이 업데이트되었습니다."}


@router.get("/bookings", response_model=List[CounselingBookingResponse])
def list_manage_bookings(
    status: Optional[str] = Query(None),
    month: Optional[str] = Query(None, description="YYYY-MM"),
    user=Depends(get_teacher_or_admin),
):
    """상담 예약 목록 (필터: status, month) — 강사/관리자 공용"""
    from datetime import date as date_type

    supabase = get_supabase()

    query = (
        supabase.table("counseling_bookings")
        .select("*")
        .order("date", desc=True)
        .order("time")
    )

    if status and status != "all":
        query = query.eq("status", status)

    if month:
        year, mon = month.split("-")
        year, mon = int(year), int(mon)
        start_date = f"{year}-{mon:02d}-01"
        end_mon = mon + 1 if mon < 12 else 1
        end_year = year if mon < 12 else year + 1
        end_date = f"{end_year}-{end_mon:02d}-01"
        query = query.gte("date", start_date).lt("date", end_date)

    res = query.execute()
    bookings = res.data or []

    return [
        CounselingBookingResponse(
            id=str(b["id"]),
            student_id=str(b.get("student_id", "")),
            student_name=b.get("student_name"),
            date=b["date"],
            time=b.get("time", ""),
            duration=b.get("duration", 30),
            reason=b.get("reason"),
            status=b.get("status", "pending"),
        )
        for b in bookings
    ]


@router.patch("/bookings/{booking_id}")
def update_booking_status(
    booking_id: str,
    body: BookingActionRequest,
    user=Depends(get_teacher_or_admin),
):
    """상담 예약 확정/취소"""
    supabase = get_supabase()

    existing = (
        supabase.table("counseling_bookings")
        .select("id, status")
        .eq("id", booking_id)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail="예약을 찾을 수 없습니다.")

    if body.status not in ("confirmed", "cancelled"):
        raise HTTPException(status_code=400, detail="유효하지 않은 상태입니다. (confirmed/cancelled)")

    supabase.table("counseling_bookings").update(
        {"status": body.status}
    ).eq("id", booking_id).execute()

    status_label = "확정" if body.status == "confirmed" else "취소"
    return {"message": f"상담 예약이 {status_label}되었습니다."}


@router.get("/blocked-slots/{date_str}")
def get_blocked_slots(date_str: str, user=Depends(get_teacher_or_admin)):
    """특정 날짜의 차단 슬롯 조회"""
    supabase = get_supabase()

    res = (
        supabase.table("counseling_blocked_slots")
        .select("time")
        .eq("counselor_id", user["id"])
        .eq("date", date_str)
        .order("time")
        .execute()
    )
    blocked = [s["time"] for s in (res.data or [])]
    return blocked
