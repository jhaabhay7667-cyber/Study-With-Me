# Study With Me
**Upload. Ask. Understand. Learn.**

A Python/FastAPI + vanilla JS implementation of the Study With Me specification. The supplied specification calls for a production-quality learning platform with authentication, uploads, AI, document/image/YouTube workflows, quizzes, flashcards, dictionary, history, library, multilingual responses, themes, responsive UI, security and deployment readiness.

## Included now
- FastAPI Python backend
- SQLite database with user/document/generation/quiz/flashcard/history/library models
- Secure password hashing (PBKDF2) and signed session tokens
- PDF/TXT/DOCX text extraction
- Image-to-AI multimodal request support through an OpenAI-compatible endpoint
- YouTube transcript extraction when captions are available
- Provider-agnostic AI service layer
- AI generation modes and source-grounded chat
- Interactive AI quizzes and flashcards
- Dictionary AI lookup
- History and My Library
- Profile, role, language, response style and theme
- Premium responsive UI with light/dark theme
- Environment variables; no secrets in frontend
- Clear AI-not-configured state instead of fake AI output

## 1. Install Python
Python 3.10+ recommended.

## 2. Create virtual environment
### Windows PowerShell
```powershell
cd study_with_me\backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 3. Configure environment
Copy `backend/.env.example` to `backend/.env` and set:
- `AI_BASE_URL`
- `AI_API_KEY`
- `AI_MODEL`
- `JWT_SECRET`

The AI endpoint must expose an OpenAI-compatible `POST /chat/completions` API. Keep the key on the backend only.

## 4. Run
```powershell
cd study_with_me\backend
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```
Open http://127.0.0.1:8000

## 5. Important behavior
If AI credentials are missing, the application launches but AI actions return a clear configuration message. It never substitutes hardcoded fake AI responses.

YouTube processing does not claim to have watched a video. It only uses an available transcript and otherwise reports that transcript access is unavailable.

## 6. Production notes
Before public deployment, move SQLite to PostgreSQL/Supabase, put uploads in object storage, add HTTPS, a production-grade OAuth provider, CSRF protection if using cookie sessions, stronger rate limiting, background jobs for very large documents, virus/malware scanning, and a reverse proxy.

## 7. Project structure
```text
study_with_me/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   └── services/
│   │       ├── ai.py
│   │       ├── documents.py
│   │       ├── image.py
│   │       └── youtube.py
│   ├── .env.example
│   └── requirements.txt
├── frontend/
│   └── index.html
├── uploads/
└── README.md
```

## 8. Scope note
Google OAuth/Supabase/PostgreSQL are represented as configuration-ready architecture points, while the default runnable build uses local email/password authentication and SQLite so it can be started immediately without requiring third-party accounts.
