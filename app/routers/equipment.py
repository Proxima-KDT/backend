from datetime import date
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends, Query
from app.dependencies import get_current_user
from app.utils.supabase_client import get_supabase
from app.schemas.equipment import (
    EquipmentResponse,
    EquipmentBorrowRequest,
    EquipmentActionResponse,
)

router = APIRouter(prefix="/api/equipment", tags=["equipment"])


@router.get("", response_model=List[EquipmentResponse])
def list_equipment(
    category: Optional[str] = Query(None, description="카테고리 필터 (노트북, 모니터, 태블릿, 주변기기)"),
    user=Depends(get_current_user),
):
    """장비 목록 조회"""
    supabase = get_supabase()
    query = supabase.table("equipment").select("*").neq("status", "retired")
    if category:
        query = query.eq("category", category)

    res = query.order("category").order("name").execute()
    items = res.data or []

    return [
        EquipmentResponse(
            id=str(item["id"]),
            name=item["name"],
            serial=item["serial"],
            category=item["category"],
            status=item["status"],
            borrower=item.get("current_borrower_name"),
            borrower_id=item.get("current_borrower_id"),
            borrowed_date=item.get("borrowed_date"),
        )
        for item in items
    ]


@router.post("/{equipment_id}/borrow", response_model=EquipmentActionResponse)
def borrow_equipment(
    equipment_id: int, body: EquipmentBorrowRequest, user=Depends(get_current_user)
):
    """장비 대여 신청"""
    supabase = get_supabase()

    # 장비 상태 확인
    eq_res = (
        supabase.table("equipment")
        .select("id, name, status")
        .eq("id", equipment_id)
        .single()
        .execute()
    )
    if not eq_res.data:
        raise HTTPException(status_code=404, detail="장비를 찾을 수 없습니다.")

    equipment = eq_res.data
    if equipment["status"] != "available":
        raise HTTPException(
            status_code=409,
            detail=f"현재 대여할 수 없는 장비입니다. (상태: {equipment['status']})",
        )

    # 프로필 조회 (이름 가져오기)
    profile_res = (
        supabase.table("profiles")
        .select("name")
        .eq("id", user["id"])
        .execute()
    )
    borrower_name = profile_res.data["name"] if profile_res.data else user.get("email", "")

    today = date.today().isoformat()

    # 장비 상태 업데이트
    supabase.table("equipment").update(
        {
            "status": "borrowed",
            "current_borrower_id": user["id"],
            "current_borrower_name": borrower_name,
            "borrowed_date": today,
        }
    ).eq("id", equipment_id).execute()

    # 대여 이력 기록
    supabase.table("equipment_requests").insert(
        {
            "equipment_id": equipment_id,
            "user_id": user["id"],
            "reason": body.reason,
            "status": "approved",
            "request_type": "borrow",
            "request_date": today,
        }
    ).execute()

    return EquipmentActionResponse(
        id=str(equipment_id),
        status="borrowed",
        message=f"'{equipment['name']}' 대여가 완료되었습니다.",
    )


@router.post("/{equipment_id}/return", response_model=EquipmentActionResponse)
def return_equipment(equipment_id: int, user=Depends(get_current_user)):
    """장비 반납"""
    supabase = get_supabase()

    eq_res = (
        supabase.table("equipment")
        .select("id, name, status, current_borrower_id")
        .eq("id", equipment_id)
        .single()
        .execute()
    )
    if not eq_res.data:
        raise HTTPException(status_code=404, detail="장비를 찾을 수 없습니다.")

    equipment = eq_res.data
    if equipment["status"] != "borrowed":
        raise HTTPException(status_code=409, detail="대여 중인 장비가 아닙니다.")
    if equipment.get("current_borrower_id") != user["id"]:
        raise HTTPException(status_code=403, detail="본인이 대여한 장비만 반납할 수 있습니다.")

    supabase.table("equipment").update(
        {
            "status": "available",
            "current_borrower_id": None,
            "current_borrower_name": None,
            "borrowed_date": None,
        }
    ).eq("id", equipment_id).execute()

    supabase.table("equipment_requests").insert(
        {
            "equipment_id": equipment_id,
            "user_id": user["id"],
            "status": "completed",
            "request_type": "return",
            "request_date": date.today().isoformat(),
        }
    ).execute()

    return EquipmentActionResponse(
        id=str(equipment_id),
        status="available",
        message=f"'{equipment['name']}' 반납이 완료되었습니다.",
    )

