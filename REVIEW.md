# REVIEW.md

While working on the starter code, I went through the attendance endpoints, validation, MongoDB queries, and analytics to understand how they behaved.

| # | Where | What I noticed | How I checked it | What I did |
|---|---|---|---|---|
| 1 | Punch-in endpoint | The starter code had a duplicate route declaration for punch-in. It was unnecessary and made the code harder to follow. | I checked the route declarations in `app/main.py`. | I kept the route declaration to one entry. |
| 2 | Attendance records | Duplicate punch-in requests could cause problems if the same employee and date were inserted more than once. | I checked the database constraints and tested the punch-in flow. | I added a unique index on `emp_code` and `date` so MongoDB prevents duplicate records. |
| 3 | Analytics queries | Analytics can become slow when attendance data grows. | I checked the query patterns and used the explain endpoint to inspect index usage. | I added indexes for common attendance queries and used MongoDB aggregation pipelines for analytics. |

## Things I checked

- The seven-day moving average uses the current day and up to six previous days.
- Weekend attendance is counted, but the attendance rate is `null` on weekends.
- Employees without attendance records should still be included in department headcount.
- MongoDB's internal `_id` is not exposed in API responses.
- Attendance corrections are recorded in history, while normal punch-in and punch-out operations do not create correction history entries.

