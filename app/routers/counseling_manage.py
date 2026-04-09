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

    # 예약 목록
    bookings_res = (
        supabase.table("counseling_bookings")
        .select("*, profiles!counseling_bookings_user_id_fkey(name)")
        .gte("date", start_date)
        .lt("date", end_date)
        .order("date")
        .order("time")
        .execute()
    )
    bookings = []
    for b in (bookings_res.data or []):
        profile = b.get("profiles") or {}
        bookings.append({
            "id": str(b["id"]),
            "student_id": str(b.get("user_id", "")),
            "student_name": profile.get("name") if isinstance(profile, dict) else None,
            "date": b["date"],
            "time": b.get("time", ""),
            "duration": b.get("duration", 30),
            "reason": b.get("reason"),
            "status": b.get("status", "pending"),
        })

    # 차단 슬롯 (is_available=False인 슬롯)
    blocked_res = (
        supabase.table("counseling_slots")
        .select("date, time_slot")
        .eq("is_available", False)
        .gte("date", start_date)
        .lt("date", end_date)
        .execute()
    )
    blocked_slots: Dict[str, List[str]] = {}
    for slot in (blocked_res.data or []):
        d = slot["date"]
        blocked_slots.setdefault(d, []).append(slot["time_slot"])

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
        supabase.table("counseling_slots")
        .select("id, time_slot, is_available")
        .eq("date", date_str)
        .execute()
    )
    existing_map = {s["time_slot"]: s for s in (existing_res.data or [])}

    # 요청된 차단 시간 처리
    for time_slot in body.blocked_times:
        if time_slot in existing_map:
            # 있으면 is_available=False로 업데이트
            supabase.table("counseling_slots").update(
                {"is_available": False}
            ).eq("id", existing_map[time_slot]["id"]).execute()
        else:
            # 없으면 새로 생성 (차단)
            supabase.table("counseling_slots").insert({
                "date": date_str,
                "time_slot": time_slot,
                "is_available": False,
                # counselor_id 없이 관리자/강사가 직접 차단
            }).execute()

    # 차단 해제: 기존에 차단이었지만 새 목록에 없는 슬롯 → is_available=True
    for time_slot, slot_data in existing_map.items():
        if time_slot not in body.blocked_times and not slot_data.get("is_available"):
            supabase.table("counseling_slots").update(
                {"is_available": True}
            ).eq("id", slot_data["id"]).execute()

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
        .select("*, profiles!counseling_bookings_user_id_fkey(name)")
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
            student_id=str(b.get("user_id", "")),
            student_name=(b.get("profiles") or {}).get("name") if isinstance(b.get("profiles"), dict) else None,
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

    # 취소 시 슬롯 다시 열기
    if body.status == "cancelled":
        booking = existing.data
        booking_detail = (
            supabase.table("counseling_bookings")
            .select("counselor_id, date, time")
            .eq("id", booking_id)
            .execute()
        )
        if booking_detail.data:
            bd = booking_detail.data
            supabase.table("counseling_slots").update(
                {"is_available": True}
            ).eq("counselor_id", bd["counselor_id"]).eq(
                "date", bd["date"]
            ).eq("time_slot", bd["time"]).execute()

    status_label = "확정" if body.status == "confirmed" else "취소"
    return {"message": f"상담 예약이 {status_label}되었습니다."}


@router.get("/blocked-slots/{date_str}")
def get_blocked_slots(date_str: str, user=Depends(get_teacher_or_admin)):
    """특정 날짜의 차단 슬롯 조회"""
    supabase = get_supabase()

    res = (
        supabase.table("counseling_slots")
        .select("time_slot")
        .eq("date", date_str)
        .eq("is_available", False)
        .order("time_slot")
        .execute()
    )
    blocked = [s["time_slot"] for s in (res.data or [])]
    return blocked
