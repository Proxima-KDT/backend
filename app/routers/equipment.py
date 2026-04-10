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
            id=item["id"],
            name=item["name"],
            serial_no=item["serial_no"],
            category=item["category"],
            status=item["status"],
            borrower_name=item.get("borrower_name"),
            borrower_id=str(item["borrower_id"]) if item.get("borrower_id") else None,
            borrowed_at=item.get("borrowed_at"),
        )
        for item in items
    ]


@router.get("/my-requests")
def get_my_requests(user=Depends(get_current_user)):
    """현재 사용자의 pending 대여 신청 목록 (equipment_id 리스트 반환)"""
    supabase = get_supabase()

    res = (
        supabase.table("equipment_requests")
        .select("equipment_id")
        .eq("user_id", user["id"])
        .eq("status", "pending")
        .execute()
    )
    pending_ids = [r["equipment_id"] for r in (res.data or [])]
    return {"pending_equipment_ids": pending_ids}


@router.post("/{equipment_id}/borrow", response_model=EquipmentActionResponse)
def borrow_equipment(
    equipment_id: int, body: EquipmentBorrowRequest, user=Depends(get_current_user)
):
    """장비 대여 신청"""
    supabase = get_supabase()

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

    # 이미 pending 요청이 있는지 확인
    existing = (
        supabase.table("equipment_requests")
        .select("id")
        .eq("equipment_id", equipment_id)
        .eq("user_id", user["id"])
        .eq("status", "pending")
        .execute()
    )
    if existing.data:
        raise HTTPException(status_code=409, detail="이미 대여 신청 중인 장비입니다.")

    # 사용자 이름 조회
    user_res = (
        supabase.table("users")
        .select("name")
        .eq("id", user["id"])
        .execute()
    )
    borrower_name = user_res.data[0]["name"] if user_res.data else user.get("email", "")

    # 대여 요청 등록 (pending) — 장비 상태는 관리자 승인 후 변경
    supabase.table("equipment_requests").insert(
        {
            "equipment_id": equipment_id,
            "equipment_name": equipment["name"],
            "user_id": user["id"],
            "student_name": borrower_name,
            "reason": body.reason,
            "status": "pending",
        }
    ).execute()

    return EquipmentActionResponse(
        id=equipment_id,
        status="pending",
        message=f"'{equipment['name']}' 대여 신청이 접수되었습니다. 관리자 승인 후 대여가 확정됩니다.",
    )


@router.post("/{equipment_id}/return", response_model=EquipmentActionResponse)
def return_equipment(equipment_id: int, user=Depends(get_current_user)):
    """장비 반납"""
    supabase = get_supabase()

    eq_res = (
        supabase.table("equipment")
        .select("id, name, status, borrower_id")
        .eq("id", equipment_id)
        .single()
        .execute()
    )
    if not eq_res.data:
        raise HTTPException(status_code=404, detail="장비를 찾을 수 없습니다.")

    equipment = eq_res.data
    if equipment["status"] != "borrowed":
        raise HTTPException(status_code=409, detail="대여 중인 장비가 아닙니다.")
    if equipment.get("borrower_id") != user["id"]:
        raise HTTPException(status_code=403, detail="본인이 대여한 장비만 반납할 수 있습니다.")

    supabase.table("equipment").update(
        {
            "status": "available",
            "borrower_id": None,
            "borrower_name": None,
            "borrowed_at": None,
        }
    ).eq("id", equipment_id).execute()

    # 반납 로그
    supabase.table("equipment_logs").insert(
        {
            "equipment_id": equipment_id,
            "user_id": user["id"],
            "action": "return",
        }
    ).execute()

    return EquipmentActionResponse(
        id=equipment_id,
        status="available",
        message=f"'{equipment['name']}' 반납이 완료되었습니다.",
    )

