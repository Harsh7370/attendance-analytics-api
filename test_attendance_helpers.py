
from datetime import datetime

from app.main import IST, compute_late_minutes


def test_late_minutes_grace_period():
    date = "2026-10-12"

    test_cases = [
        ("09:40:00", 0),
        ("09:40:01", 10),
        ("10:15:59", 45),
    ]

    for time_str, expected in test_cases:
        punch_in = datetime.fromisoformat(
            f"{date}T{time_str}"
        ).replace(tzinfo=IST)

        actual = compute_late_minutes(
            punch_in,
            "09:30",
            date,
        )

        assert actual == expected, (
            f"For {time_str}, expected {expected}, "
            f"but got {actual}"
        )


def test_punch_in_exactly_at_shift_start():
    date = "2026-10-12"

    punch_in = datetime.fromisoformat(
        f"{date}T09:30:00"
    ).replace(tzinfo=IST)

    actual = compute_late_minutes(
        punch_in,
        "09:30",
        date,
    )

    assert actual == 0


def test_punch_in_before_shift_start():
    date = "2026-10-12"

    punch_in = datetime.fromisoformat(
        f"{date}T09:20:00"
    ).replace(tzinfo=IST)

    actual = compute_late_minutes(
        punch_in,
        "09:30",
        date,
    )

    assert actual == 0
