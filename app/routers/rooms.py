from typing import List
from fastapi import APIRouter, HTTPException, Depends, Query
from app.dependencies import get_current_user
from app.utils.supabase_client import get_supabase
from app.schemas.room import (
    RoomResponse,
    BookedSlotResponse,
    ReservationCreateRequest,
    ReservationResponse,
)

router = APIRouter(prefix="/api/rooms", tags=["rooms"])


@router.get("", response_model=List[RoomResponse])
def list_rooms(user=Depends(get_current_user)):
    """강의실/스터디룸 목록 조회"""
    supabase = get_supabase()
    res = supabase.table("rooms").select("*").execute()
    rooms = res.data or []

    return [
        RoomResponse(
            id=str(r["id"]),
            name=r["name"],
            type=r.get("type", "study"),
            status=r.get("status", "available"),
            capacity=r.get("capacity", 0),
            floor=r.get("floor"),
            amenities=r.get("amenities") or [],
        )
        for r in rooms
    ]


@router.get("/{room_id}/slots", response_model=List[BookedSlotResponse])
def get_room_slots(
    room_id: str,
    date: str = Query(..., description="YYYY-MM-DD"),
    user=Depends(get_current_user),
):
    """특정 날짜의 예약 현황 조회"""
    supabase = get_supabase()

    res = (
        supabase.table("room_reservations")
        .select("*, rooms(name, type)")
        .eq("room_id", room_id)
        .eq("date", date)
        .neq("status", "cancelled")
        .execute()
    )
    slots = res.data or []

    return [
        BookedSlotResponse(
            room_id=str(s["room_id"]),
            date=s["date"],
            start_time=s["start_time"],
            end_time=s["end_time"],
            reserved_by=s.get("purpose"),
            is_mine=(s.get("user_id") == user["id"]),
            purpose=s.get("purpose"),
        )
        for s in slots
    ]


@router.get("/my-reservations", response_model=List[ReservationResponse])
def my_reservations(user=Depends(get_current_user)):
    """내 예약 목록 조회"""
    supabase = get_supabase()

    res = (
        supabase.table("room_reservations")
        .select("*, rooms(name, type)")
        .eq("user_id", user["id"])
        .neq("status", "cancelled")
        .order("date", desc=True)
        .execute()
    )
    reservations = res.data or []

    return [
        ReservationResponse(
            id=str(r["id"]),
            room_id=str(r["room_id"]),
            room_name=r.get("rooms", {}).get("name") if r.get("rooms") else None,
            room_type=r.get("rooms", {}).get("type") if r.get("rooms") else None,
            date=r["date"],
            start_time=r["start_time"],
            end_time=r["end_time"],
            purpose=r.get("purpose"),
            status=r.get("status", "confirmed"),
        )
        for r in reservations
    ]


@router.post("/reserve", response_model=ReservationResponse)
def create_reservation(body: ReservationCreateRequest, user=Depends(get_current_user)):
    """예약 생성"""
    supabase = get_supabase()

    # 시간 충돌 확인
    conflict_res = (
        supabase.table("room_reservations")
        .select("id")
        .eq("room_id", body.room_id)
        .eq("date", body.date)
        .neq("status", "cancelled")
        .lt("start_time", body.end_time)
        .gt("end_time", body.start_time)
        .execute()
    )
    if conflict_res.data:
        raise HTTPException(status_code=409, detail="해당 시간대에 이미 예약이 있습니다.")

    # 방 정보 조회 (insert 시 비정규화 컬럼에 함께 저장)
    room_res = (
        supabase.table("rooms").select("name, type").eq("id", body.room_id).maybe_single().execute()
    )
    room_data = room_res.data or {}

    # 사용자 이름 조회
    user_res = supabase.table("users").select("name").eq("id", user["id"]).execute()
    user_name = user_res.data[0]["name"] if user_res.data else None

    res = (
        supabase.table("room_reservations")
        .insert(
            {
                "room_id": body.room_id,
                "user_id": user["id"],
                "user_name": user_name,
                "room_name": room_data.get("name"),
                "room_type": room_data.get("type"),
                "date": body.date,
                "start_time": body.start_time,
                "end_time": body.end_time,
                "purpose": body.purpose,
                "status": "confirmed",
            }
        )
        .execute()
    )
    r = res.data[0]

    return ReservationResponse(
        id=str(r["id"]),
        room_id=str(r["room_id"]),
        room_name=room_data.get("name"),
        room_type=room_data.get("type"),
        date=r["date"],
        start_time=r["start_time"],
        end_time=r["end_time"],
        purpose=r.get("purpose"),
        status=r.get("status", "confirmed"),
    )


@router.delete("/reservations/{reservation_id}")
def cancel_reservation(reservation_id: str, user=Depends(get_current_user)):
    """예약 취소"""
    supabase = get_supabase()

    res = (
        supabase.table("room_reservations")
        .select("id, user_id, status")
        .eq("id", reservation_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="예약을 찾을 수 없습니다.")
    reservation = res.data[0]
    if reservation.get("user_id") != user["id"]:
        raise HTTPException(status_code=403, detail="본인의 예약만 취소할 수 있습니다.")
    if reservation.get("status") == "cancelled":
        raise HTTPException(status_code=409, detail="이미 취소된 예약입니다.")

    supabase.table("room_reservations").update({"status": "cancelled"}).eq(
        "id", reservation_id
    ).execute()
    return {"message": "예약이 취소되었습니다."}

