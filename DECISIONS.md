# DECISIONS.md

### 1. Indexes
I added a unique index on `emp_code` for employees and another on `(emp_code, date)` for attendance. These prevent duplicate employees and duplicate daily attendance records. I also added indexes for date-based attendance queries and finding an employee's latest record. I considered an index on department and joining date for headcount lookups, but I'd test its benefit before keeping it.

### 2. Punch-in race
If two punch-in requests arrive together, both might initially find no record. The unique attendance index is the final safeguard: only one insert can succeed. The other request needs to be handled as a `409 Conflict`.

### 3. Ties
Employees with the same late minutes get the same rank. If a tie reaches the leaderboard limit, I return everyone whose rank is within the limit, even if the result contains extra employees.

### 4. Headcount
The department summary starts with employees who joined by the end of the month and then looks up their attendance records. This includes employees who have no attendance logs.

### 5. Scaling up
With 100 times more data, I'd test the slowest queries using `explain` and realistic data, then tune the indexes and aggregation pipelines based on the results.