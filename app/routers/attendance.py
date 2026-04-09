from datetime import date, datetime
from fastapi import APIRouter, HTTPException, Depends
from app.dependencies import get_current_user
from app.utils.supabase_client import get_supabase
from app.schemas.attendance import (
    CheckInRequest,
    AttendanceRecordResponse,
    AttendanceMonthlyResponse,
)

router = APIRouter(prefix="/api/attendance", tags=["attendance"])

CHECKIN_LATE_HOUR = 9
CHECKIN_LATE_MINUTE = 10


@router.get("/today", response_model=AttendanceRecordResponse)
def get_today_attendance(user=Depends(get_current_user)):
    """오늘의 출석 기록 조회"""
    supabase = get_supabase()
    today = date.today().isoformat()

    res = (
        supabase.table("attendance")
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
        check_out_time=r.get("check_out_time"),
    )


@router.post("/check-in")
def check_in(body: CheckInRequest, user=Depends(get_current_user)):
    """출석 체크인 (서명 포함)"""
    supabase = get_supabase()
    today = date.today().isoformat()
    now = datetime.now()
    time_str = now.strftime("%H:%M")

    existing = (
        supabase.table("attendance")
        .select("id")
        .eq("user_id", user["id"])
        .eq("date", today)
        .execute()
    )
    if existing.data:
        raise HTTPException(status_code=409, detail="이미 오늘 출석 체크인이 완료되었습니다.")

    payload = {
        "user_id": user["id"],
        "date": today,
        "check_in_time": time_str,
        "status": "checked_in",
    }
    if body.signature_url:
        payload["signature_image"] = body.signature_url

    supabase.table("attendance").insert(payload).execute()
    return {"message": "입실 완료", "status": "checked_in", "time": time_str}


@router.post("/check-out")
def check_out(user=Depends(get_current_user)):
    """퇴실 체크아웃"""
    supabase = get_supabase()
    today = date.today().isoformat()
    time_str = datetime.now().strftime("%H:%M")

    existing = (
        supabase.table("attendance")
        .select("id, check_out_time, check_in_time, status")
        .eq("user_id", user["id"])
        .eq("date", today)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status_code=400, detail="오늘 출석 기록이 없습니다.")
    rec = existing.data[0]
    if rec.get("check_out_time"):
        raise HTTPException(status_code=409, detail="이미 퇴실 처리되었습니다.")

    # 퇴실 시 최종 출결 상태 결정 (체크인 시각 기준)
    check_in_time = rec.get("check_in_time", "09:00")
    h, m = map(int, check_in_time.split(":"))
    late_limit = CHECKIN_LATE_HOUR * 60 + CHECKIN_LATE_MINUTE
    final_status = "late" if (h * 60 + m) > late_limit else "present"

    supabase.table("attendance").update(
        {"check_out_time": time_str, "status": final_status}
    ).eq("id", rec["id"]).execute()
    return {"message": "퇴실 완료", "status": final_status, "time": time_str}


@router.get("/monthly", response_model=AttendanceMonthlyResponse)
def get_monthly_attendance(
    year: int = None, month: int = None, user=Depends(get_current_user)
):
    """월별 출석 현황 조회"""
    supabase = get_supabase()
    today = date.today()
    year = year or today.year
    month = month or today.month

    start_date = f"{year}-{month:02d}-01"
    if month == 12:
        end_date = f"{year + 1}-01-01"
    else:
        end_date = f"{year}-{month + 1:02d}-01"

    res = (
        supabase.table("attendance")
        .select("date, status, check_in_time")
        .eq("user_id", user["id"])
        .gte("date", start_date)
        .lt("date", end_date)
        .execute()
    )
    records = res.data or []

    stat = {"present": 0, "late": 0, "absent": 0, "early_leave": 0, "checked_in": 0}
    for r in records:
        s = r.get("status")
        if s in stat:
            stat[s] += 1

    total_days = len(records)
    attended = stat["present"] + stat["late"]
    rate = round((attended / total_days) * 100, 1) if total_days > 0 else 0.0

    return AttendanceMonthlyResponse(
        year=year,
        month=month,
        total_days=total_days,
        present=stat["present"],
        late=stat["late"],
        absent=stat["absent"],
        rate=rate,
        records=[
            {"date": r["date"], "status": r.get("status"), "time": r.get("check_in_time")}
            for r in records
        ],
    )


@router.post("/early-leave")
def early_leave(user=Depends(get_current_user)):
    """조퇴 처리"""
    supabase = get_supabase()
    today = date.today().isoformat()
    time_str = datetime.now().strftime("%H:%M")

    existing = (
        supabase.table("attendance")
        .select("id, status, check_out_time")
        .eq("user_id", user["id"])
        .eq("date", today)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status_code=400, detail="오늘 출석 기록이 없습니다.")
    rec = existing.data[0]
    if rec.get("check_out_time"):
        raise HTTPException(status_code=409, detail="이미 퇴실 처리되었습니다.")

    supabase.table("attendance").update(
        {"check_out_time": time_str, "status": "early_leave"}
    ).eq("id", rec["id"]).execute()
    return {"message": "조퇴 처리 완료", "status": "early_leave", "time": time_str}


def _count_weekdays(start: date, end: date) -> int:
    """start~end(포함) 사이 평일(월-금) 수를 계산한다."""
    count = 0
    current = start
    from datetime import timedelta
    while current <= end:
        if current.weekday() < 5:
            count += 1
        current += timedelta(days=1)
    return count


@router.get("/summary")
def get_attendance_summary(user=Depends(get_current_user)):
    """훈련 시작일부터 오늘까지 전체 출석 요약을 반환한다.
    - training_start: 커리큘럼 1단계 시작일
    - total_weekdays: 시작일~오늘 평일 수
    - attended: 출석+지각 일수
    - absent: 결석 일수
    - rate: 출석률 (%)
    """
    supabase = get_supabase()
    today = date.today()

    # 커리큘럼 1단계 시작일 조회
    cur_res = (
        supabase.table("curriculum")
        .select("start_date")
        .eq("phase", 1)
        .execute()
    )
    if not cur_res.data:
        training_start = today
    else:
        training_start = date.fromisoformat(str(cur_res.data[0]["start_date"]))

    total_weekdays = _count_weekdays(training_start, today)

    # 전체 출석 기록 조회
    att_res = (
        supabase.table("attendance")
        .select("date, status")
        .eq("user_id", user["id"])
        .gte("date", training_start.isoformat())
        .lte("date", today.isoformat())
        .execute()
    )
    records = att_res.data or []

    attended = sum(1 for r in records if r.get("status") in ("present", "late"))
    late = sum(1 for r in records if r.get("status") == "late")
    absent_count = total_weekdays - attended
    rate = round((attended / total_weekdays) * 100, 1) if total_weekdays > 0 else 0.0

    return {
        "training_start": training_start.isoformat(),
        "today": today.isoformat(),
        "total_weekdays": total_weekdays,
        "attended": attended,
        "late": late,
        "absent": max(0, absent_count),
        "rate": rate,
    }

