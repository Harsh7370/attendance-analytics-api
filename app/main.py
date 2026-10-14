"""
Employee Attendance & Analytics API - STARTER

Run:  uvicorn app.main:app --port 8000
Env:  MONGO_URI, MONGO_DB (a local .env is loaded for convenience)

This file was written quickly by a colleague who has left the company. The happy path
works, but nobody has reviewed it. Read PROBLEM_STATEMENT.docx for what is expected of you,
openapi.yaml for the contract and DATA_MODEL.md for what is stored in MongoDB.
"""
import os
import calendar
from datetime import datetime, timedelta, timezone, date
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from pymongo import MongoClient
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal, Optional
from pymongo.errors import DuplicateKeyError 
from  pymongo import ReturnDocument
from pydantic import BaseModel, Field, StrictInt

load_dotenv()

client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))
db = client[os.getenv("MONGO_DB", "attendance_db")]

IST = timezone(timedelta(hours=5, minutes=30))

app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0")


def ensure_indexes():
    db.employees.create_index(
        [("emp_code", 1)],
        unique=True,
        name="uq_employee_emp_code"
    )

    db.attendance_logs.create_index(
        [("emp_code", 1), ("date", 1)],
        unique=True,
        name="uq_attendance_emp_date"
    )

    db.attendance_logs.create_index(
        [("date", -1), ("emp_code", 1)],
        name="ix_attendance_date_emp"
    )

    db.attendance_logs.create_index(
        [("emp_code", 1), ("date", -1)],
        name="ix_attendance_emp_date_desc"
    )


@app.on_event("startup")
def startup():
    ensure_indexes()



# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def normalize_timestamp(ts: datetime) -> datetime:
    """Convert an instant to IST and remove fractional seconds."""
    if ts.tzinfo is None:
        # MongoDB BSON datetimes are UTC; treat naive values as UTC.
        ts = ts.replace(tzinfo=timezone.utc)

    return ts.astimezone(IST).replace(microsecond=0)



def timestamp_from_epoch_ms(value: Optional[int] = None) -> datetime:
    """Convert epoch milliseconds to a whole-second UTC datetime."""
    if value is None:
        ts = datetime.now(timezone.utc)
    else:
        ts = datetime.fromtimestamp(value / 1000, tz=timezone.utc)

    return ts.replace(microsecond=0)



def attendance_date_for_punch_in(
    punch_in: datetime,
    shift_start: str,
    shift_end: str,
) -> str:
    """Return the IST attendance date, including overnight shifts."""
    local_time = normalize_timestamp(punch_in)
    start_hour, start_minute = map(int, shift_start.split(":"))
    end_hour, end_minute = map(int, shift_end.split(":"))

    start_minutes = start_hour * 60 + start_minute
    end_minutes = end_hour * 60 + end_minute
    punch_minutes = local_time.hour * 60 + local_time.minute

    # If an overnight shift ends after midnight, early punches
    # before shift_end belong to the previous day's shift.
    if end_minutes <= start_minutes and punch_minutes < end_minutes:
        return (local_time.date() - timedelta(days=1)).isoformat()

    return local_time.date().isoformat()



def compute_late_minutes(
    punch_in: datetime,
    shift_start: str,
    date_str: str,
) -> int:
    """Calculate lateness using IST wall-clock time."""
    punch_in_ist = normalize_timestamp(punch_in)
    h, m = map(int, shift_start.split(":"))

    shift_start_dt = datetime.fromisoformat(date_str).replace(
        hour=h,
        minute=m,
        second=0,
        microsecond=0,
        tzinfo=IST,
    )

    elapsed_seconds = int(
        (punch_in_ist - shift_start_dt).total_seconds()
    )

    return elapsed_seconds // 60 if elapsed_seconds > 600 else 0



def compute_work_hours(
    punch_in: datetime,
    punch_out: datetime,
) -> float:
    """Calculate elapsed hours, rounded half-up to two decimals."""
    punch_in = normalize_timestamp(punch_in)
    punch_out = normalize_timestamp(punch_out)

    seconds = int((punch_out - punch_in).total_seconds())
    hours = Decimal(seconds) / Decimal(3600)

    return float(
        hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    )


def compute_overtime(
    punch_out: datetime,
    shift_start: str,
    shift_end: str,
    date_str: str,
) -> int:
    """Count overtime only when it reaches at least 30 minutes."""
    punch_out = normalize_timestamp(punch_out)

    start_h, start_m = map(int, shift_start.split(":"))
    end_h, end_m = map(int, shift_end.split(":"))

    shift_start_minutes = start_h * 60 + start_m
    shift_end_minutes = end_h * 60 + end_m

    shift_end_dt = datetime.fromisoformat(date_str).replace(
        hour=end_h,
        minute=end_m,
        second=0,
        microsecond=0,
        tzinfo=IST,
    )

    # For overnight shifts, the shift ends on the next calendar day.
    if shift_end_minutes <= shift_start_minutes:
        shift_end_dt += timedelta(days=1)

    elapsed_seconds = int((punch_out - shift_end_dt).total_seconds())
    overtime_minutes = elapsed_seconds // 60

    return overtime_minutes if overtime_minutes >= 30 else 0



# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class EmployeeIn(BaseModel):
    emp_code: str
    name: str
    email: str
    department: str
    shift_start: str = "09:30"
    shift_end: str = "18:30"
    joined_on: str


class PunchInIn(BaseModel):
    emp_code: str
    punched_at: StrictInt | None = Field(
        default=None,
        ge=100_000_000_000,
        le=253_402_300_799_999
    )
    status: Literal["PRESENT", "WFH", "ON_DUTY"] = "PRESENT"


class PunchOutIn(BaseModel):
    emp_code: str
    punched_at: StrictInt | None = Field(
        default=None,
        ge=100_000_000_000,
        le=253_402_300_799_999
    )


class RegularizeRequest(BaseModel):
    reason: str
    regularized_by: str
    status: Literal[
        "PRESENT", "ABSENT", "LEAVE", "WFH", "ON_DUTY"
    ] | None = None
    punch_in: StrictInt | None = Field(
        default=None,
        ge=100_000_000_000,
        le=253_402_300_799_999
    )
    punch_out: StrictInt | None = Field(
        default=None,
        ge=100_000_000_000,
        le=253_402_300_799_999
    )



# --------------------------------------------------------------------------- #
# Endpoints provided
# --------------------------------------------------------------------------- #

@app.get("/health")
def health():
    try:
        db.command("ping")
        return {"status": "ok"}
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable"
        )




@app.post("/employees", status_code=201)
def create_employee(body: EmployeeIn):
    if body.shift_start == body.shift_end:
        raise HTTPException(
            status_code=422,
            detail="shift_start and shift_end must differ"
        )

    doc = body.model_dump()
    doc["created_at"] = datetime.now(timezone.utc)

    try:
        db.employees.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=409,
            detail="emp_code already exists"
        )

    doc.pop("_id", None)
    return doc





@app.get("/employees")
def list_employees(
    department: Optional[str] = None,
    page: int = 1,
    page_size: int = 20
):
    if page < 1:
        raise HTTPException(
            status_code=422,
            detail="page must be at least 1"
        )

    if page_size < 1 or page_size > 100:
        raise HTTPException(
            status_code=422,
            detail="page_size must be between 1 and 100"
        )

    q = {}

    if department:
        q["department"] = department

    skip = (page - 1) * page_size
    total = db.employees.count_documents(q)

    items = list(
        db.employees.find(q, {"_id": 0})
        .sort("emp_code", 1)
        .skip(skip)
        .limit(page_size)
    )

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size
    }




@app.post("/attendance/punch-in", status_code=201)
def punch_in(body: PunchInIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})

    if emp is None:
        raise HTTPException(status_code=404, detail="employee not found")

    ts_utc = timestamp_from_epoch_ms(body.punched_at)
    ts_ist = normalize_timestamp(ts_utc)

    attendance_date = attendance_date_for_punch_in(
        ts_ist,
        emp["shift_start"],
        emp["shift_end"],
    )

    doc = {
        "emp_code": body.emp_code,
        "date": attendance_date,
        "status": body.status,
        "punch_in": ts_utc,
        "punch_out": None,
        "work_hours": None,
        "late_minutes": compute_late_minutes(
            ts_ist,
            emp["shift_start"],
            attendance_date,
        ),
        "overtime_minutes": 0,
        "half_day": False,
        "history": [],
    }

    try:
        db.attendance_logs.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=409,
            detail="already punched in for this date",
        )

   
    # Return only API fields; never expose MongoDB's internal _id.
    return {
        "emp_code": doc["emp_code"],
        "date": doc["date"],
        "status": doc["status"],
        "punch_in": int(ts_utc.timestamp() * 1000),
        "punch_out": None,
        "work_hours": None,
        "late_minutes": doc["late_minutes"],
        "overtime_minutes": 0,
        "half_day": False,
        "history": [],
    }



@app.get("/attendance")
def list_attendance(
    emp_code: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
):
    if page < 1:
        raise HTTPException(
            status_code=422,
            detail="page must be at least 1"
        )

    if page_size < 1 or page_size > 100:
        raise HTTPException(
            status_code=422,
            detail="page_size must be between 1 and 100"
        )

    # Validate date format and calendar validity.
    for value, field in (
        (date_from, "date_from"),
        (date_to, "date_to"),
    ):
        if value is not None:
            try:
                datetime.strptime(value, "%Y-%m-%d")
                if len(value) != 10:
                    raise ValueError
            except ValueError:
                raise HTTPException(
                    status_code=422,
                    detail=f"{field} must be a valid YYYY-MM-DD date"
                )

    if date_from and date_to and date_from > date_to:
        raise HTTPException(
            status_code=422,
            detail="date_from must not be after date_to"
        )

    allowed_statuses = {
        "PRESENT", "ABSENT", "LEAVE", "WFH", "ON_DUTY"
    }
    if status is not None and status not in allowed_statuses:
        raise HTTPException(
            status_code=422,
            detail="Invalid attendance status"
        )

    q = {}

    if emp_code:
        q["emp_code"] = emp_code

    if date_from or date_to:
        q["date"] = {}
        if date_from:
            q["date"]["$gte"] = date_from
        if date_to:
            q["date"]["$lte"] = date_to

    if status:
        q["status"] = status

    total = db.attendance_logs.count_documents(q)

    docs = list(
        db.attendance_logs.find(q, {"_id": 0})
        .sort([("date", -1), ("emp_code", 1)])
        .skip((page - 1) * page_size)
        .limit(page_size)
    )

    return {
        "items": docs,
        "total": total,
        "page": page,
        "page_size": page_size
    }


@app.post("/attendance/punch-out")
def punch_out(body: PunchOutIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})

    if emp is None:
        raise HTTPException(status_code=404, detail="employee not found")

    punch_out_utc = timestamp_from_epoch_ms(body.punched_at)

    # Find the most recent attendance record whose punch-in
    # occurred at or before the requested punch-out instant.
    record = db.attendance_logs.find_one(
        {
            "emp_code": body.emp_code,
            "punch_in": {"$lte": punch_out_utc},
        },
        sort=[("punch_in", -1)],
    )

    if record is None:
        raise HTTPException(
            status_code=404,
            detail="no punch-in found",
        )

    if record["punch_out"] is not None:
        raise HTTPException(
            status_code=409,
            detail="already punched out",
        )

    punch_in_utc = record["punch_in"].replace(tzinfo=timezone.utc)
    punch_in_ist = normalize_timestamp(punch_in_utc)
    punch_out_ist = normalize_timestamp(punch_out_utc)

    if punch_out_utc <= punch_in_utc:
        raise HTTPException(
            status_code=422,
            detail="punch-out must be after punch-in",
        )

    if (punch_out_utc - punch_in_utc).total_seconds() > 24 * 3600:
        raise HTTPException(
            status_code=422,
            detail="punch-out cannot be more than 24 hours after punch-in",
        )

    work_hours = compute_work_hours(punch_in_ist, punch_out_ist)

    overtime_minutes = compute_overtime(
        punch_out_ist,
        emp["shift_start"],
        emp["shift_end"],
        record["date"],
    )

    half_day = work_hours < 4.50

    updated = db.attendance_logs.find_one_and_update(
        {
            "_id": record["_id"],
            "punch_out": None,
        },
        {
            "$set": {
                "punch_out": punch_out_utc,
                "work_hours": work_hours,
                "overtime_minutes": overtime_minutes,
                "half_day": half_day,
            }
        },
        return_document=ReturnDocument.AFTER,
    )

    if updated is None:
        raise HTTPException(
            status_code=409,
            detail="already punched out",
        )

    return {
        "emp_code": updated["emp_code"],
        "date": updated["date"],
        "status": updated["status"],
        "punch_in": int(punch_in_utc.timestamp() * 1000),
        "punch_out": int(punch_out_utc.timestamp() * 1000),
        "work_hours": updated["work_hours"],
        "late_minutes": updated["late_minutes"],
        "overtime_minutes": updated["overtime_minutes"],
        "half_day": updated["half_day"],
        "history": updated.get("history", []),
    }


@app.patch("/attendance/{emp_code}/{date}")
def regularize_attendance(
    emp_code: str,
    date: str,
    body: RegularizeRequest,
):
    emp = db.employees.find_one({"emp_code": emp_code})
    if emp is None:
        raise HTTPException(status_code=404, detail="employee not found")

    record = db.attendance_logs.find_one(
        {"emp_code": emp_code, "date": date}
    )
    if record is None:
        raise HTTPException(status_code=404, detail="attendance record not found")

    if not body.reason.strip() or not body.regularized_by.strip():
        raise HTTPException(
            status_code=422,
            detail="reason and regularized_by must not be empty",
        )

    allowed_statuses = {"PRESENT", "ABSENT", "LEAVE", "WFH", "ON_DUTY"}
    new_status = body.status if body.status is not None else record["status"]

    if new_status not in allowed_statuses:
        raise HTTPException(status_code=422, detail="invalid status")

    changes_requested = body.model_fields_set
    new_punch_in = record["punch_in"]
    new_punch_out = record["punch_out"]

    if "punch_in" in changes_requested:
        new_punch_in = (
            timestamp_from_epoch_ms(body.punch_in)
            if body.punch_in is not None
            else None
        )

    if "punch_out" in changes_requested:
        new_punch_out = (
            timestamp_from_epoch_ms(body.punch_out)
            if body.punch_out is not None
            else None
        )

    if new_status in {"ABSENT", "LEAVE"}:
        if (
            ("punch_in" in changes_requested and body.punch_in is not None)
            or ("punch_out" in changes_requested and body.punch_out is not None)
        ):
            raise HTTPException(
                status_code=422,
                detail="ABSENT and LEAVE cannot have punch times",
            )
        new_punch_in = None
        new_punch_out = None
    elif new_punch_in is None:
        raise HTTPException(
            status_code=422,
            detail="presence status requires punch_in",
        )

    if new_punch_in is not None:
        local_in = normalize_timestamp(new_punch_in)
        expected_date = attendance_date_for_punch_in(
            local_in, emp["shift_start"], emp["shift_end"]
        )
        if expected_date != date:
            raise HTTPException(
                status_code=422,
                detail="punch_in must belong to the attendance date",
            )

    if new_punch_out is not None:
        if new_punch_in is None or new_punch_out <= new_punch_in:
            raise HTTPException(
                status_code=422,
                detail="punch_out must be after punch_in",
            )
        if (new_punch_out - new_punch_in).total_seconds() > 24 * 3600:
            raise HTTPException(
                status_code=422,
                detail="punch_out cannot be more than 24 hours after punch_in",
            )

    if new_punch_in is not None and new_punch_out is not None:
        local_in = normalize_timestamp(new_punch_in)
        local_out = normalize_timestamp(new_punch_out)
        work_hours = compute_work_hours(local_in, local_out)
        overtime_minutes = compute_overtime(
            local_out,
            emp["shift_start"],
            emp["shift_end"],
            date,
        )
        half_day = work_hours < 4.50
    else:
        work_hours = None
        overtime_minutes = 0
        half_day = False

    late_minutes = (
        compute_late_minutes(
            normalize_timestamp(new_punch_in),
            emp["shift_start"],
            date,
        )
        if new_punch_in is not None
        else 0
    )

    new_values = {
        "status": new_status,
        "punch_in": new_punch_in,
        "punch_out": new_punch_out,
        "work_hours": work_hours,
        "late_minutes": late_minutes,
        "overtime_minutes": overtime_minutes,
        "half_day": half_day,
    }

    changes = {}
    for field, new_value in new_values.items():
        old_value = record.get(field)
        if old_value != new_value:
            if field in {"punch_in", "punch_out"}:
                old_value = (
                    int(old_value.replace(tzinfo=timezone.utc).timestamp() * 1000)
                    if old_value is not None else None
                )
                converted_new = (
                    int(new_value.timestamp() * 1000)
                    if new_value is not None else None
                )
                changes[field] = {"from": old_value, "to": converted_new}
            else:
                changes[field] = {"from": record.get(field), "to": new_value}

    if not changes:
        raise HTTPException(status_code=422, detail="no changes to apply")

    history_entry = {
        "at": datetime.now(timezone.utc).replace(microsecond=0),
        "by": body.regularized_by.strip(),
        "reason": body.reason.strip(),
        "changes": changes,
    }

    updated = db.attendance_logs.find_one_and_update(
        {
            "_id": record["_id"],
            "status": record["status"],
            "punch_in": record["punch_in"],
            "punch_out": record["punch_out"],
            "history": record.get("history", []),
        },
        {
            "$set": new_values,
            "$push": {"history": history_entry},
        },
        return_document=ReturnDocument.AFTER,
    )

    if updated is None:
        raise HTTPException(
            status_code=409,
            detail="attendance record changed concurrently; retry the correction",
        )

    def to_epoch_ms(value):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return int(value.timestamp() * 1000)

    return {
        "emp_code": updated["emp_code"],
        "date": updated["date"],
        "status": updated["status"],
        "punch_in": to_epoch_ms(updated["punch_in"]),
        "punch_out": to_epoch_ms(updated["punch_out"]),
        "work_hours": updated["work_hours"],
        "late_minutes": updated["late_minutes"],
        "overtime_minutes": updated["overtime_minutes"],
        "half_day": updated["half_day"],
        "history": [
            {
                "at": to_epoch_ms(item["at"]),
                "by": item["by"],
                "reason": item["reason"],
                "changes": item["changes"],
            }
            for item in updated.get("history", [])
        ],
    }





@app.get("/analytics/employees/{emp_code}/monthly")
def employee_monthly(emp_code: str, month: str):
    # Validate YYYY-MM.
    try:
        if len(month) != 7:
            raise ValueError
        year, month_number = map(int, month.split("-"))
        if not 1 <= month_number <= 12:
            raise ValueError
        first_day = date(year, month_number, 1)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=422,
            detail="month must be in YYYY-MM format"
        )

    emp = db.employees.find_one({"emp_code": emp_code})
    if emp is None:
        raise HTTPException(status_code=404, detail="employee not found")

    last_day = date(
        year,
        month_number,
        calendar.monthrange(year, month_number)[1]
    )

    # Count Monday-Friday working days from the later of
    # the month start and the employee's joining date.
    joined_on = date.fromisoformat(emp["joined_on"])
    start_day = max(first_day, joined_on)

    working_days = 0
    current_day = start_day
    while current_day <= last_day:
        if current_day.weekday() < 5:
            working_days += 1
        current_day += timedelta(days=1)

    # MongoDB performs the attendance aggregation.
    pipeline = [
        {
            "$match": {
                "emp_code": emp_code,
                "date": {
                    "$gte": first_day.isoformat(),
                    "$lte": last_day.isoformat()
                }
            }
        },
        {
            "$group": {
                "_id": None,
                "present_days": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    {"$in": ["$status", ["PRESENT", "WFH", "ON_DUTY"]]},
                                    {
                                        "$in": [
                                            {"$dayOfWeek": {
                                                "$dateFromString": {
                                                    "dateString": "$date",
                                                    "format": "%Y-%m-%d"
                                                }
                                            }},
                                            [2, 3, 4, 5, 6]
                                        ]
                                    }
                                ]
                            },
                            {
                                "$cond": [
                                    "$half_day",
                                    0.5,
                                    1
                                ]
                            },
                            0
                        ]
                    }
                },
                "leave_days": {
                    "$sum": {
                        "$cond": [{"$eq": ["$status", "LEAVE"]}, 1, 0]
                    }
                },
                "late_count": {
                    "$sum": {
                        "$cond": [{"$gt": ["$late_minutes", 0]}, 1, 0]
                    }
                },
                "total_late_minutes": {"$sum": "$late_minutes"},
                "total_overtime_minutes": {"$sum": "$overtime_minutes"}
            }
        }
    ]

    results = list(db.attendance_logs.aggregate(pipeline))
    stats = results[0] if results else {}

    present_days = float(stats.get("present_days", 0))
    attendance_pct = (
    float(
        (Decimal(str(present_days)) / Decimal(working_days) * Decimal("100"))
        .quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    )
    if working_days > 0
    else None
)

    return {
        "emp_code": emp_code,
        "month": month,
        "working_days": working_days,
        "present_days": present_days,
        "leave_days": stats.get("leave_days", 0),
        "late_count": stats.get("late_count", 0),
        "total_late_minutes": stats.get("total_late_minutes", 0),
        "total_overtime_minutes": stats.get("total_overtime_minutes", 0),
        "attendance_pct": attendance_pct
    }


@app.get("/analytics/departments/summary")
def department_summary(month: str, department: str | None = None):
    # Validate YYYY-MM
    try:
        if len(month) != 7 or month[4] != "-":
            raise ValueError
        year, month_number = map(int, month.split("-"))
        first_day = date(year, month_number, 1)
        last_day = date(
            year,
            month_number,
            calendar.monthrange(year, month_number)[1],
        )
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=422,
            detail="month must be in YYYY-MM format",
        )

    start = first_day.isoformat()
    end = last_day.isoformat()

    # Employees who have joined by the end of the requested month.
    employee_match = {"joined_on": {"$lte": end}}
    if department is not None:
        employee_match["department"] = department

    pipeline = [
        {"$match": employee_match},
        {
            "$lookup": {
                "from": "attendance_logs",
                "let": {"code": "$emp_code", "dept": "$department"},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {"$eq": ["$emp_code", "$$code"]},
                            "date": {"$gte": start, "$lte": end},
                        }
                    },
                    {
                        "$group": {
                            "_id": None,
                            "present_days": {
                                "$sum": {
                                    "$cond": [
                                        {
                                            "$and": [
                                                {
                                                    "$in": [
                                                        "$status",
                                                        ["PRESENT", "WFH", "ON_DUTY"],
                                                    ]
                                                },
                                                {
                                                    "$in": [
                                                        {
                                                            "$dayOfWeek": {
                                                                "$dateFromString": {
                                                                    "dateString": "$date",
                                                                    "format": "%Y-%m-%d",
                                                                }
                                                            }
                                                        },
                                                        [2, 3, 4, 5, 6],
                                                    ]
                                                },
                                            ]
                                        },
                                        {"$cond": ["$half_day", 0.5, 1]},
                                        0,
                                    ]
                                }
                            },
                            "work_hours_sum": {
                                "$sum": {
                                    "$cond": [
                                        {
                                            "$and": [
                                                {
                                                    "$in": [
                                                        "$status",
                                                        ["PRESENT", "WFH", "ON_DUTY"],
                                                    ]
                                                },
                                                {"$ne": ["$work_hours", None]},
                                            ]
                                        },
                                        "$work_hours",
                                        0,
                                    ]
                                }
                            },
                            "work_hours_count": {
                                "$sum": {
                                    "$cond": [
                                        {
                                            "$and": [
                                                {
                                                    "$in": [
                                                        "$status",
                                                        ["PRESENT", "WFH", "ON_DUTY"],
                                                    ]
                                                },
                                                {"$ne": ["$work_hours", None]},
                                            ]
                                        },
                                        1,
                                        0,
                                    ]
                                }
                            },
                            "late_count": {
                                "$sum": {
                                    "$cond": [
                                        {"$gt": ["$late_minutes", 0]},
                                        1,
                                        0,
                                    ]
                                }
                            },
                            "total_late_minutes": {"$sum": "$late_minutes"},
                            "leave_count": {
                                "$sum": {
                                    "$cond": [
                                        {"$eq": ["$status", "LEAVE"]},
                                        1,
                                        0,
                                    ]
                                }
                            },
                            "on_duty_count": {
                                "$sum": {
                                    "$cond": [
                                        {"$eq": ["$status", "ON_DUTY"]},
                                        1,
                                        0,
                                    ]
                                }
                            },
                        }
                    },
                ],
                "as": "stats",
            }
        },
        {
            "$set": {
                "stats": {
                    "$ifNull": [
                        {"$arrayElemAt": ["$stats", 0]},
                        {
                            "present_days": 0,
                            "work_hours_sum": 0,
                            "work_hours_count": 0,
                            "late_count": 0,
                            "total_late_minutes": 0,
                            "leave_count": 0,
                            "on_duty_count": 0,
                        },
                    ]
                }
            }
        },
        {
            "$group": {
                "_id": "$department",
                "headcount": {"$sum": 1},
                "present_days": {"$sum": "$stats.present_days"},
                "work_hours_sum": {"$sum": "$stats.work_hours_sum"},
                "work_hours_count": {"$sum": "$stats.work_hours_count"},
                "late_count": {"$sum": "$stats.late_count"},
                "total_late_minutes": {"$sum": "$stats.total_late_minutes"},
                "leave_count": {"$sum": "$stats.leave_count"},
                "on_duty_count": {"$sum": "$stats.on_duty_count"},
            }
        },
       
        {
            "$project": {
                "_id": 0,
                "department": "$_id",
                "headcount": 1,
                "present_days": 1,
                "avg_work_hours": None,
                "work_hours_sum": 1,
                "work_hours_count": 1,
                "late_count": 1,
                "total_late_minutes": 1,
                "leave_count": 1,
                "on_duty_count": 1,
            }
        },
        {"$sort": {"department": 1}},
    ]

    items = list(db.employees.aggregate(pipeline))

    for item in items:
        total = item.pop("work_hours_sum", 0)
        count = item.pop("work_hours_count", 0)

        item["avg_work_hours"] = (
            float(
                (Decimal(str(total)) / Decimal(count)).quantize(
                    Decimal("0.01"),
                    rounding=ROUND_HALF_UP,
                )
            )
            if count > 0
            else None
        )

    return {"month": month, "items": items}



@app.get("/analytics/leaderboard/late")
def late_leaderboard(
    month: str,
    limit: int = 10,
    department: str | None = None,
):
    # Validate month and limit
    try:
        if len(month) != 7 or month[4] != "-":
            raise ValueError
        year, month_number = map(int, month.split("-"))
        first_day = date(year, month_number, 1)
        last_day = date(
            year,
            month_number,
            calendar.monthrange(year, month_number)[1],
        )
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=422,
            detail="month must be in YYYY-MM format",
        )

    if not 1 <= limit <= 50:
        raise HTTPException(
            status_code=422,
            detail="limit must be between 1 and 50",
        )

    start = first_day.isoformat()
    end = last_day.isoformat()

    pipeline = [
        {
            "$match": {
                "date": {"$gte": start, "$lte": end},
                "late_minutes": {"$gt": 0},
            }
        },
        {
            "$group": {
                "_id": "$emp_code",
                "total_late_minutes": {"$sum": "$late_minutes"},
                "late_count": {"$sum": 1},
            }
        },
        {
            "$lookup": {
                "from": "employees",
                "localField": "_id",
                "foreignField": "emp_code",
                "as": "employee",
            }
        },
        {"$unwind": "$employee"},
    ]

    if department is not None:
        pipeline.append(
            {"$match": {"employee.department": department}}
        )

    pipeline.extend(
        [
            {
                "$setWindowFields": {
                    "sortBy": {
                        "total_late_minutes": -1,
                    },
                    "output": {
                        "rank": {"$rank": {}},
                    },
                }
            },
            {
                "$sort": {
                    "total_late_minutes": -1,
                    "_id": 1,
                }
            },
            {"$match": {"rank": {"$lte": limit}}},
            {
                "$project": {
                    "_id": 0,
                    "rank": 1,
                    "emp_code": "$_id",
                    "name": "$employee.name",
                    "department": "$employee.department",
                    "total_late_minutes": 1,
                    "late_count": 1,
                }
            },
        ]
    )

    items = list(db.attendance_logs.aggregate(pipeline))

    return {"month": month, "items": items}


@app.get("/analytics/departments/{department}/trend")
def department_trend(
    department: str,
    from_date: str = Query(alias="from"),
    to_date: str = Query(alias="to"),
):
    # Validate dates
    try:
        start_day = date.fromisoformat(from_date)
        end_day = date.fromisoformat(to_date)

        if start_day.isoformat() != from_date or end_day.isoformat() != to_date:
            raise ValueError
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="'from' and 'to' must be dates in YYYY-MM-DD format",
        )

    if end_day < start_day:
        raise HTTPException(status_code=422, detail="'to' must not be before 'from'")

    if (end_day - start_day).days + 1 > 92:
        raise HTTPException(status_code=422, detail="date range cannot exceed 92 days")

    # Ensure the department exists
    if db.employees.count_documents({"department": department}) == 0:
        raise HTTPException(status_code=404, detail="department not found")

    pipeline = [
        {
            "$match": {
                "date": {
                    "$gte": from_date,
                    "$lte": to_date,
                }
            }
        },
        {
            "$lookup": {
                "from": "employees",
                "localField": "emp_code",
                "foreignField": "emp_code",
                "as": "employee",
            }
        },
        {"$unwind": "$employee"},
        {"$match": {"employee.department": department}},
        {
            "$group": {
                "_id": "$date",
                "present_count": {
                    "$sum": {
                        "$cond": [
                            {
                                "$in": [
                                    "$status",
                                    ["PRESENT", "WFH", "ON_DUTY"],
                                ]
                            },
                            {"$cond": ["$half_day", 0.5, 1]},
                            0,
                        ]
                    }
                },
                "late_count": {
                    "$sum": {
                        "$cond": [{"$gt": ["$late_minutes", 0]}, 1, 0]
                    }
                },
            }
        },
        {
            "$project": {
                "_id": 0,
                "date": {
                    "$dateFromString": {
                        "dateString": "$_id",
                        "format": "%Y-%m-%d",
                    }
                },
                "present_count": 1,
                "late_count": 1,
            }
        },
        {
            "$densify": {
                "field": "date",
                "range": {
                    "step": 1,
                    "unit": "day",
                    "bounds": [
                        datetime.combine(start_day, datetime.min.time()),
                        datetime.combine(end_day + timedelta(days=1), datetime.min.time()),
                    ],
                },
            }
        },
        {
            "$set": {
                "present_count": {"$ifNull": ["$present_count", 0]},
                "late_count": {"$ifNull": ["$late_count", 0]},
                "is_working_day": {
                    "$and": [
                        {"$gte": [{"$dayOfWeek": "$date"}, 2]},
                        {"$lte": [{"$dayOfWeek": "$date"}, 6]},
                    ]
                },
            }
        },
        {
            "$lookup": {
                "from": "employees",
                "let": {"current_date": "$date"},
                "pipeline": [
                    {
                        "$match": {
                            "department": department,
                            "$expr": {
                                "$lte": [
                                    "$joined_on",
                                    {
                                        "$dateToString": {
                                            "format": "%Y-%m-%d",
                                            "date": "$$current_date",
                                        }
                                    },
                                ]
                            },
                        }
                    },
                    {"$count": "headcount"},
                ],
                "as": "headcount_result",
            }
        },
        {
            "$set": {
                "headcount": {
                    "$ifNull": [
                        {"$arrayElemAt": ["$headcount_result.headcount", 0]},
                        0,
                    ]
                }
            }
        },
        {
            "$set": {
                "attendance_rate": {
                    "$cond": [
                        {
                            "$and": [
                                "$is_working_day",
                                {"$gt": ["$headcount", 0]},
                            ]
                        },
                        {"$divide": ["$present_count", "$headcount"]},
                        None,
                    ]
                }
            }
        },
        {
            "$setWindowFields": {
                "sortBy": {"date": 1},
                "output": {
                    "moving_avg_7d": {
                        "$avg": "$attendance_rate",
                        "window": {"documents": [-6, 0]},
                    }
                },
            }
        },
        {
            "$project": {
                "_id": 0,
                "date": {
                    "$dateToString": {
                        "format": "%Y-%m-%d",
                        "date": "$date",
                    }
                },
                "is_working_day": 1,
                "headcount": 1,
                "present_count": 1,
                "late_count": 1,
                "attendance_rate": 1,
                "moving_avg_7d": 1,
            }
        },
        {"$sort": {"date": 1}},
    ]

    items = list(db.attendance_logs.aggregate(pipeline))

    # Apply the contract's four-decimal HALF_UP rounding.
    for item in items:
        for field in ("attendance_rate", "moving_avg_7d"):
            value = item[field]
            item[field] = (
                float(
                    Decimal(str(value)).quantize(
                        Decimal("0.0001"),
                        rounding=ROUND_HALF_UP,
                    )
                )
                if value is not None
                else None
            )

    return {"department": department, "items": items}



@app.get("/admin/explain/{endpoint}")
def explain_endpoint(
    endpoint: Literal[
        "attendance_list",
        "employee_monthly",
        "department_summary",
        "late_leaderboard",
        "department_trend",
    ],
    emp_code: str | None = None,
    month: str | None = None,
    department: str | None = None,
    limit: int = 10,
    date_from: str | None = None,
    date_to: str | None = None,
    status: str | None = None,
    from_date: str | None = Query(default=None, alias="from"),
    to_date: str | None = Query(default=None, alias="to"),
    page: int = 1,
    page_size: int = 20,
):
    # Validate common pagination parameters.
    if page < 1 or not 1 <= page_size <= 100:
        raise HTTPException(
            status_code=422,
            detail="page must be >= 1 and page_size must be between 1 and 100",
        )

    if not 1 <= limit <= 50:
        raise HTTPException(
            status_code=422,
            detail="limit must be between 1 and 50",
        )

    # Build the same filter, sort and pagination as attendance_list.
    if endpoint == "attendance_list":
        filters = {}

        if emp_code is not None:
            filters["emp_code"] = emp_code
        if status is not None:
            if status not in [
                "PRESENT", "ABSENT", "LEAVE", "WFH", "ON_DUTY"
            ]:
                raise HTTPException(422, detail="Invalid status")
            filters["status"] = status
        if date_from is not None:
            filters.setdefault("date", {})["$gte"] = date_from
        if date_to is not None:
            filters.setdefault("date", {})["$lte"] = date_to

        if date_from and date_to and date_from > date_to:
            raise HTTPException(
                status_code=422,
                detail="date_from must not be after date_to",
            )

        explain = db.command(
            "explain",
            {
                "find": "attendance_logs",
                "filter": filters,
                "sort": {"date": -1, "emp_code": 1},
                "skip": (page - 1) * page_size,
                "limit": page_size,
            },
            verbosity="executionStats",
        )

        return {
            "endpoint": endpoint,
            "collection": "attendance_logs",
            "explain": explain,
        }

    
    if endpoint == "employee_monthly":
        # Both parameters are required for this endpoint.
        if not emp_code or not month:
            raise HTTPException(
                status_code=422,
                detail="emp_code and month are required"
            )

        # Validate YYYY-MM, matching employee_monthly.
        try:
            if len(month) != 7:
                raise ValueError
            year, month_number = map(int, month.split("-"))
            if not 1 <= month_number <= 12:
                raise ValueError
            first_day = date(year, month_number, 1)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=422,
                detail="month must be in YYYY-MM format"
            )

        # Match the original endpoint's employee existence check.
        emp = db.employees.find_one({"emp_code": emp_code})
        if emp is None:
            raise HTTPException(
                status_code=404,
                detail="employee not found"
            )

        last_day = date(
            year,
            month_number,
            calendar.monthrange(year, month_number)[1]
        )

        # Use the same aggregation pipeline as employee_monthly.
        pipeline = [
            {
                "$match": {
                    "emp_code": emp_code,
                    "date": {
                        "$gte": first_day.isoformat(),
                        "$lte": last_day.isoformat()
                    }
                }
            },
            {
                "$group": {
                    "_id": None,
                    "present_days": {
                        "$sum": {
                            "$cond": [
                                {
                                    "$and": [
                                        {
                                            "$in": [
                                                "$status",
                                                ["PRESENT", "WFH", "ON_DUTY"]
                                            ]
                                        },
                                        {
                                            "$in": [
                                                {
                                                    "$dayOfWeek": {
                                                        "$dateFromString": {
                                                            "dateString": "$date",
                                                            "format": "%Y-%m-%d"
                                                        }
                                                    }
                                                },
                                                [2, 3, 4, 5, 6]
                                            ]
                                        }
                                    ]
                                },
                                {
                                    "$cond": [
                                        "$half_day",
                                        0.5,
                                        1
                                    ]
                                },
                                0
                            ]
                        }
                    },
                    "leave_days": {
                        "$sum": {
                            "$cond": [
                                {"$eq": ["$status", "LEAVE"]},
                                1,
                                0
                            ]
                        }
                    },
                    "late_count": {
                        "$sum": {
                            "$cond": [
                                {"$gt": ["$late_minutes", 0]},
                                1,
                                0
                            ]
                        }
                    },
                    "total_late_minutes": {"$sum": "$late_minutes"},
                    "total_overtime_minutes": {"$sum": "$overtime_minutes"}
                }
            }
        ]

        explain = db.command(
            "explain",
            {
                "aggregate": "attendance_logs",
                "pipeline": pipeline,
                "cursor": {}
            },
            verbosity="executionStats"
        )

        return {
            "endpoint": endpoint,
            "collection": "attendance_logs",
            "explain": explain
        }

    
    if endpoint == "department_summary":
        if not month:
            raise HTTPException(
                status_code=422,
                detail="month is required"
            )

        # Validate YYYY-MM and calculate the month boundaries.
        try:
            if len(month) != 7 or month[4] != "-":
                raise ValueError

            year, month_number = map(int, month.split("-"))

            first_day = date(year, month_number, 1)
            last_day = date(
                year,
                month_number,
                calendar.monthrange(year, month_number)[1],
            )
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=422,
                detail="month must be in YYYY-MM format",
            )

        start = first_day.isoformat()
        end = last_day.isoformat()

        # Match the filters used by department_summary.
        employee_match = {"joined_on": {"$lte": end}}

        if department is not None:
            employee_match["department"] = department

        # Explain the same aggregation pipeline as the endpoint.
        pipeline = [
            {"$match": employee_match},
            {
                "$lookup": {
                    "from": "attendance_logs",
                    "let": {"code": "$emp_code", "dept": "$department"},
                    "pipeline": [
                        {
                            "$match": {
                                "$expr": {"$eq": ["$emp_code", "$$code"]},
                                "date": {"$gte": start, "$lte": end},
                            }
                        },
                        {
                            "$group": {
                                "_id": None,
                                "present_days": {
                                    "$sum": {
                                        "$cond": [
                                            {
                                                "$and": [
                                                    {
                                                        "$in": [
                                                            "$status",
                                                            ["PRESENT", "WFH", "ON_DUTY"],
                                                        ]
                                                    },
                                                    {
                                                        "$in": [
                                                            {
                                                                "$dayOfWeek": {
                                                                    "$dateFromString": {
                                                                        "dateString": "$date",
                                                                        "format": "%Y-%m-%d",
                                                                    }
                                                                }
                                                            },
                                                            [2, 3, 4, 5, 6],
                                                        ]
                                                    },
                                                ]
                                            },
                                            {"$cond": ["$half_day", 0.5, 1]},
                                            0,
                                        ]
                                    }
                                },
                                "work_hours_sum": {
                                    "$sum": {
                                        "$cond": [
                                            {
                                                "$and": [
                                                    {
                                                        "$in": [
                                                            "$status",
                                                            ["PRESENT", "WFH", "ON_DUTY"],
                                                        ]
                                                    },
                                                    {"$ne": ["$work_hours", None]},
                                                ]
                                            },
                                            "$work_hours",
                                            0,
                                        ]
                                    }
                                },
                                "work_hours_count": {
                                    "$sum": {
                                        "$cond": [
                                            {
                                                "$and": [
                                                    {
                                                        "$in": [
                                                            "$status",
                                                            ["PRESENT", "WFH", "ON_DUTY"],
                                                        ]
                                                    },
                                                    {"$ne": ["$work_hours", None]},
                                                ]
                                            },
                                            1,
                                            0,
                                        ]
                                    }
                                },
                                "late_count": {
                                    "$sum": {
                                        "$cond": [
                                            {"$gt": ["$late_minutes", 0]},
                                            1,
                                            0,
                                        ]
                                    }
                                },
                                "total_late_minutes": {"$sum": "$late_minutes"},
                                "leave_count": {
                                    "$sum": {
                                        "$cond": [
                                            {"$eq": ["$status", "LEAVE"]},
                                            1,
                                            0,
                                        ]
                                    }
                                },
                                "on_duty_count": {
                                    "$sum": {
                                        "$cond": [
                                            {"$eq": ["$status", "ON_DUTY"]},
                                            1,
                                            0,
                                        ]
                                    }
                                },
                            }
                        },
                    ],
                    "as": "stats",
                }
            },
            {
                "$set": {
                    "stats": {
                        "$ifNull": [
                            {"$arrayElemAt": ["$stats", 0]},
                            {
                                "present_days": 0,
                                "work_hours_sum": 0,
                                "work_hours_count": 0,
                                "late_count": 0,
                                "total_late_minutes": 0,
                                "leave_count": 0,
                                "on_duty_count": 0,
                            },
                        ]
                    }
                }
            },
            {
                "$group": {
                    "_id": "$department",
                    "headcount": {"$sum": 1},
                    "present_days": {"$sum": "$stats.present_days"},
                    "work_hours_sum": {"$sum": "$stats.work_hours_sum"},
                    "work_hours_count": {"$sum": "$stats.work_hours_count"},
                    "late_count": {"$sum": "$stats.late_count"},
                    "total_late_minutes": {"$sum": "$stats.total_late_minutes"},
                    "leave_count": {"$sum": "$stats.leave_count"},
                    "on_duty_count": {"$sum": "$stats.on_duty_count"},
                }
            },
            {
                "$project": {
                    "_id": 0,
                    "department": "$_id",
                    "headcount": 1,
                    "present_days": 1,
                    "avg_work_hours": None,
                    "work_hours_sum": 1,
                    "work_hours_count": 1,
                    "late_count": 1,
                    "total_late_minutes": 1,
                    "leave_count": 1,
                    "on_duty_count": 1,
                }
            },
            {"$sort": {"department": 1}},
        ]

        explain = db.command(
            "explain",
            {
                "aggregate": "employees",
                "pipeline": pipeline,
                "cursor": {},
            },
            verbosity="executionStats",
        )

        return {
            "endpoint": endpoint,
            "collection": "employees",
            "explain": explain,
        }

    
    if endpoint == "late_leaderboard":
        if not month:
            raise HTTPException(
                status_code=422,
                detail="month is required"
            )

        # Validate month.
        try:
            if len(month) != 7 or month[4] != "-":
                raise ValueError

            year, month_number = map(int, month.split("-"))
            first_day = date(year, month_number, 1)
            last_day = date(
                year,
                month_number,
                calendar.monthrange(year, month_number)[1],
            )
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=422,
                detail="month must be in YYYY-MM format",
            )

        if not 1 <= limit <= 50:
            raise HTTPException(
                status_code=422,
                detail="limit must be between 1 and 50",
            )

        start = first_day.isoformat()
        end = last_day.isoformat()

        pipeline = [
            {
                "$match": {
                    "date": {"$gte": start, "$lte": end},
                    "late_minutes": {"$gt": 0},
                }
            },
            {
                "$group": {
                    "_id": "$emp_code",
                    "total_late_minutes": {"$sum": "$late_minutes"},
                    "late_count": {"$sum": 1},
                }
            },
            {
                "$lookup": {
                    "from": "employees",
                    "localField": "_id",
                    "foreignField": "emp_code",
                    "as": "employee",
                }
            },
            {"$unwind": "$employee"},
        ]

        if department is not None:
            pipeline.append(
                {"$match": {"employee.department": department}}
            )

        pipeline.extend(
            [
                {
                    "$setWindowFields": {
                        "sortBy": {
                            "total_late_minutes": -1,
                        },
                        "output": {
                            "rank": {"$rank": {}},
                        },
                    }
                },
                {
                    "$sort": {
                        "total_late_minutes": -1,
                        "_id": 1,
                    }
                },
                {"$match": {"rank": {"$lte": limit}}},
                {
                    "$project": {
                        "_id": 0,
                        "rank": 1,
                        "emp_code": "$_id",
                        "name": "$employee.name",
                        "department": "$employee.department",
                        "total_late_minutes": 1,
                        "late_count": 1,
                    }
                },
            ]
        )

        explain = db.command(
            "explain",
            {
                "aggregate": "attendance_logs",
                "pipeline": pipeline,
                "cursor": {},
            },
            verbosity="executionStats",
        )

        return {
            "endpoint": endpoint,
            "collection": "attendance_logs",
            "explain": explain,
        }

    
    if endpoint == "department_trend":
        if not department or not from_date or not to_date:
            raise HTTPException(
                status_code=422,
                detail="department, from and to are required",
            )

        # Validate dates in YYYY-MM-DD format.
        try:
            start_day = date.fromisoformat(from_date)
            end_day = date.fromisoformat(to_date)

            if (
                start_day.isoformat() != from_date
                or end_day.isoformat() != to_date
            ):
                raise ValueError
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail="'from' and 'to' must be dates in YYYY-MM-DD format",
            )

        if end_day < start_day:
            raise HTTPException(
                status_code=422,
                detail="'to' must not be before 'from'",
            )

        if (end_day - start_day).days + 1 > 92:
            raise HTTPException(
                status_code=422,
                detail="date range cannot exceed 92 days",
            )

        if db.employees.count_documents(
            {"department": department}
        ) == 0:
            raise HTTPException(
                status_code=404,
                detail="department not found",
            )

        pipeline = [
            {
                "$match": {
                    "date": {
                        "$gte": from_date,
                        "$lte": to_date,
                    }
                }
            },
            {
                "$lookup": {
                    "from": "employees",
                    "localField": "emp_code",
                    "foreignField": "emp_code",
                    "as": "employee",
                }
            },
            {"$unwind": "$employee"},
            {"$match": {"employee.department": department}},
            {
                "$group": {
                    "_id": "$date",
                    "present_count": {
                        "$sum": {
                            "$cond": [
                                {
                                    "$in": [
                                        "$status",
                                        ["PRESENT", "WFH", "ON_DUTY"],
                                    ]
                                },
                                {"$cond": ["$half_day", 0.5, 1]},
                                0,
                            ]
                        }
                    },
                    "late_count": {
                        "$sum": {
                            "$cond": [
                                {"$gt": ["$late_minutes", 0]},
                                1,
                                0,
                            ]
                        }
                    },
                }
            },
            {
                "$project": {
                    "_id": 0,
                    "date": {
                        "$dateFromString": {
                            "dateString": "$_id",
                            "format": "%Y-%m-%d",
                        }
                    },
                    "present_count": 1,
                    "late_count": 1,
                }
            },
            {
                "$densify": {
                    "field": "date",
                    "range": {
                        "step": 1,
                        "unit": "day",
                        "bounds": [
                            datetime.combine(
                                start_day, datetime.min.time()
                            ),
                            datetime.combine(end_day + timedelta(days=1), datetime.min.time()
                            ),
                        ],
                    },
                }
            },
            {
                "$set": {
                    "present_count": {
                        "$ifNull": ["$present_count", 0]
                    },
                    "late_count": {
                        "$ifNull": ["$late_count", 0]
                    },
                    "is_working_day": {
                        "$and": [
                            {"$gte": [{"$dayOfWeek": "$date"}, 2]},
                            {"$lte": [{"$dayOfWeek": "$date"}, 6]},
                        ]
                    },
                }
            },
            {
                "$lookup": {
                    "from": "employees",
                    "let": {"current_date": "$date"},
                    "pipeline": [
                        {
                            "$match": {
                                "department": department,
                                "$expr": {
                                    "$lte": [
                                        "$joined_on",
                                        {
                                            "$dateToString": {
                                                "format": "%Y-%m-%d",
                                                "date": "$$current_date",
                                            }
                                        },
                                    ]
                                },
                            }
                        },
                        {"$count": "headcount"},
                    ],
                    "as": "headcount_result",
                }
            },
            {
                "$set": {
                    "headcount": {
                        "$ifNull": [
                            {
                                "$arrayElemAt": [
                                    "$headcount_result.headcount",
                                    0,
                                ]
                            },
                            0,
                        ]
                    }
                }
            },
            {
                "$set": {
                    "attendance_rate": {
                        "$cond": [
                            {
                                "$and": [
                                    "$is_working_day",
                                    {"$gt": ["$headcount", 0]},
                                ]
                            },
                            {
                                "$divide": [
                                    "$present_count",
                                    "$headcount",
                                ]
                            },
                            None,
                        ]
                    }
                }
            },
            {
                "$setWindowFields": {
                    "sortBy": {"date": 1},
                    "output": {
                        "moving_avg_7d": {
                            "$avg": "$attendance_rate",
                            "window": {"documents": [-6, 0]},
                        }
                    },
                }
            },
            {
                "$project": {
                    "_id": 0,
                    "date": {
                        "$dateToString": {
                            "format": "%Y-%m-%d",
                            "date": "$date",
                        }
                    },
                    "is_working_day": 1,
                    "headcount": 1,
                    "present_count": 1,
                    "late_count": 1,
                    "attendance_rate": 1,
                    "moving_avg_7d": 1,
                }
            },
            {"$sort": {"date": 1}},
        ]

        explain = db.command(
            "explain",
            {
                "aggregate": "attendance_logs",
                "pipeline": pipeline,
                "cursor": {},
            },
            verbosity="executionStats",
        )

        return {
            "endpoint": endpoint,
            "collection": "attendance_logs",
            "explain": explain,
        }





    # Other branches will be added next, using their exact pipelines.
    raise HTTPException(
        status_code=422,
        detail=f"Explain query for {endpoint} is not implemented yet",
    )





# --------------------------------------------------------------------------- #
# TODO - the rest of the contract (see openapi.yaml):
#   POST  /attendance/punch-out
#   PATCH /attendance/{emp_code}/{date}
#   GET   /analytics/employees/{emp_code}/monthly
#   GET   /analytics/departments/summary
#   GET   /analytics/leaderboard/late
#   GET   /analytics/departments/{department}/trend
#   GET   /admin/explain/{endpoint}
# --------------------------------------------------------------------------- #
