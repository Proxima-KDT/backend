from datetime import date, datetime
from fastapi import APIRouter, HTTPException, Depends
from app.dependencies import get_current_user
from app.utils.supabase_client import get_supabase
from app.schemas.attendance import (
    CheckInRequest,
    EarlyLeaveRequest,
    AttendanceRecordResponse,
    AttendanceMonthlyResponse,
)

router = APIRouter(prefix="/api/attendance", tags=["attendance"])

CHECKIN_LATE_HOUR = 9
CHECKIN_LATE_MINUTE = 10  # 09:10 이후 출석 → 지각


@router.get("/today", response_model=AttendanceRecordResponse)
def get_today_attendance(user=Depends(get_current_user)):
    """오늘의 출석 기록 조회"""
    supabase = get_supabase()
    today = date.today().isoformat()

    res = (
        supabase.table("attendance_records")
        .select("*")
        .eq("user_id", user["id"])
        .eq("date", today)
        .execute()
    )
    if not res.data:
        return AttendanceRecordResponse(date=today, status=None, time=None)

    r = res.data[0]
    return AttendanceRecordResponse(
        date=r["date"],
        status=r["status"],
        time=r.get("check_in_time"),
    )


@router.post("/check-in")
def check_in(body: CheckInRequest, user=Depends(get_current_user)):
    """출석 체크인 (서명 포함)"""
    supabase = get_supabase()
    today = date.today().isoformat()
    now = datetime.now()
    time_str = now.strftime("%H:%M")

    # 중복 체크인 방지
    existing = (
        supabase.table("attendance_records")
        .select("id")
        .eq("user_id", user["id"])
        .eq("date", today)
        .execute()
    )
    if existing.data:
        raise HTTPException(status_code=409, detail="이미 오늘 출석 체크인이 완료되었습니다.")

    # 지각 여부 판단
    late_threshold = now.replace(hour=CHECKIN_LATE_HOUR, minute=CHECKIN_LATE_MINUTE, second=0, microsecond=0)
    status = "late" if now > late_threshold else "present"

    payload = {
        "user_id": user["id"],
        "date": today,
        "check_in_time": time_str,
        "status": status,
    }
    if body.signature_url:
        payload["signature_url"] = body.signature_url

    supabase.table("attendance_records").insert(payload).execute()
    return {"message": "출석 완료", "status": status, "time": time_str}


@router.post("/check-out")
def check_out(user=Depends(get_current_user)):
    """퇴실 체크아웃"""
    supabase = get_supabase()
    today = date.today().isoformat()
    time_str = datetime.now().strftime("%H:%M")

    existing = (
        supabase.table("attendance_records")
        .select("id, check_out_time")
        .eq("user_id", user["id"])
        .eq("date", today)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status_code=400, detail="오늘 출석 기록이 없습니다.")
    if existing.data[0].get("check_out_time"):
        raise HTTPException(status_code=409, detail="이미 퇴실 처리되었습니다.")

    supabase.table("attendance_records").update({"check_out_time": time_str}).eq(
        "id", existing.data[0]["id"]
    ).execute()
    return {"message": "퇴실 완료", "time": time_str}


@router.post("/early-leave")
def request_early_leave(body: EarlyLeaveRequest, user=Depends(get_current_user)):
    """조기 퇴실 신청"""
    supabase = get_supabase()
    today = date.today().isoformat()

    # 오늘 기록 확인
    existing = (
        supabase.table("attendance_records")
        .select("id")
        .eq("user_id", user["id"])
        .eq("date", today)
        .execute()
    )
    record_id = existing.data[0]["id"] if existing.data else None

    # early_leave_requests 테이블에 삽입
    supabase.table("early_leave_requests").insert(
        {
            "user_id": user["id"],
            "date": today,
            "reason": body.reason,
            "status": "pending",
        }
    ).execute()

    # 출석 상태를 early_leave로 업데이트
    if record_id:
        supabase.table("attendance_records").update({"status": "early_leave"}).eq(
            "id", record_id
        ).execute()

    return {"message": "조기 퇴실 신청이 완료되었습니다."}


@router.get("/monthly", response_model=AttendanceMonthlyResponse)
def get_monthly_attendance(
    year: int = None, month: int = None, user=Depends(get_current_user)
):
    """월별 출석 현황 조회"""
    supabase = get_supabase()
    today = date.today()
    year = year or today.year
    month = month or today.month

    # 해당 월 범위 (YYYY-MM-01 ~ YYYY-MM-DD)
    start_date = f"{year}-{month:02d}-01"
    if month == 12:
        end_date = f"{year + 1}-01-01"
    else:
        end_date = f"{year}-{month + 1:02d}-01"

    res = (
        supabase.table("attendance_records")
        .select("date, status, check_in_time")
        .eq("user_id", user["id"])
        .gte("date", start_date)
        .lt("date", end_date)
        .execute()
    )
    records = res.data or []

    stat = {"present": 0, "late": 0, "absent": 0, "early_leave": 0}
    for r in records:
        s = r.get("status")
        if s in stat:
            stat[s] += 1

    total_days = len(records)
    attended = stat["present"] + stat["late"] + stat["early_leave"]
    rate = round((attended / total_days) * 100, 1) if total_days > 0 else 0.0

    return AttendanceMonthlyResponse(
        year=year,
        month=month,
        total_days=total_days,
        present=stat["present"],
        late=stat["late"],
        absent=stat["absent"],
        early_leave=stat["early_leave"],
        rate=rate,
        records=[
            {"date": r["date"], "status": r.get("status"), "time": r.get("check_in_time")}
            for r in records
        ],
    )

