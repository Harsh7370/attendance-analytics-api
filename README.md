# Employee Attendance & Analytics API

I built this project using Python, FastAPI, and MongoDB to manage employee attendance and generate useful analytics. It covers daily punch-in and punch-out, attendance corrections, and department-wise reporting.

## Features

- Employee creation and listing
- Punch-in and punch-out with validation
- Manual attendance corrections with an audit trail
- Monthly attendance analytics
- Department-wise attendance summaries
- Late-arrival leaderboard with ranking and tie handling
- Department attendance trends with a seven-day moving average
- MongoDB indexes to prevent duplicate attendance records
- Query execution statistics for checking database performance

## Tech Stack

- Python
- FastAPI
- MongoDB
- PyMongo
- Pytest

## Getting Started

### 1. Create a virtual environment

```bash
python -m venv .venv
```

Activate it on Windows:

```powershell
.venv\Scripts\Activate.ps1
```

### 2. Install dependencies

```bash
python -m pip install -r requirements.txt
```

### 3. Start MongoDB

Make sure MongoDB is running locally or configure your MongoDB connection using the `MONGO_URI` and `MONGO_DB` environment variables.

### 4. Load sample data

```bash
python sample_seed.py
```

**Note:** This script clears the existing `employees` and `attendance_logs` collections before loading sample data. Run it only when you are okay with replacing those records.

### 5. Run the API

```bash
python -m uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/docs` to explore the API endpoints.

## Run Tests

```bash
python -m pytest test_attendance_helpers.py -v
```

## Project Structure

- `app/main.py` — API endpoints and business logic
- `sample_seed.py` — Loads sample data into MongoDB
- `sample_data/` — Sample employee and attendance records
- `test_attendance_helpers.py` — Attendance helper tests
- `DATA_MODEL.md` — Database structure
- `DECISIONS.md` — Design choices and trade-offs
- `REVIEW.md` — Review of the starter code
- `openapi.yaml` — API specification