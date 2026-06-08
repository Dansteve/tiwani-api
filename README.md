# Tiwani API

This is the FastAPI backend for the Tiwani project.

## Features

- FastAPI backend for user, child, chapter, and trigger management
- Supabase integration for auth and database operations
- CORS enabled for frontend interaction
- Swagger UI available at `/api/docs`
- ReDoc available at `/api/redoc`

## Setup

1. Create a Python virtual environment:

```bash
cd tiwani-api
python3 -m venv venv
source venv/bin/activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Copy environment example and update values:

```bash
cp .env.example .env
```

4. Update `.env` with your Supabase project values:

- `SUPABASE_URL`
- `SUPABASE_KEY`
- `SUPABASE_SERVICE_ROLE_KEY`
- `DATABASE_URL`

## Run

```bash
./start.sh
```

Then open the Swagger UI at:

- `http://localhost:8000/api/docs`

OpenAPI JSON is available at:

- `http://localhost:8000/api/openapi.json`

ReDoc is available at:

- `http://localhost:8000/api/redoc`

## Notes

- The app currently uses Supabase auth and the `profiles`, `children`, `chapters`, and `triggers` tables.
- If you want secure CORS in production, replace `allow_origins=["*"]` in `main.py` with your frontend origin.
