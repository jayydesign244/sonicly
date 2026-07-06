# EigenTalk — AI Audio Editor

A clean, minimal AI-powered audio editing web app. Built with React (frontend) and FastAPI (backend).

## Project Structure

```
AI Audio Editor/
├── frontend/          # React + Vite + Tailwind CSS
└── backend/           # FastAPI (Python)
```

## Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

Runs at **http://localhost:3000**

## Backend Setup

```bash
cd backend
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Runs at **http://localhost:8000**  
API docs at **http://localhost:8000/docs**

## Screens

| # | Screen | Route |
|---|---|---|
| 1 | Landing Page | `/` |
| 2 | Sign Up | `/signup` |
| 3 | Log In | `/login` |
| 4 | Dashboard | `/dashboard` |
| 5 | Processing | `/processing` |
| 6 | Editor | `/editor` |

## Tech Stack

**Frontend**
- React 18 + React Router v6
- Tailwind CSS v3
- Vite

**Backend**
- FastAPI
- Pydantic v2
- Uvicorn
