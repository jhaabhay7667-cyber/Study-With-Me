from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional, List
import sqlite3, os, secrets, hashlib, mimetypes, re, json
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1]/".env")

from .services.ai import AIService, AIConfigError, AIServiceError
from .services.documents import extract_document
from .services.youtube import extract_youtube_transcript
from .services.image import image_to_data_url

BASE = Path(__file__).resolve().parents[2]
DB_PATH = BASE / 'data.db'
UPLOAD_DIR = BASE / 'uploads'
UPLOAD_DIR.mkdir(exist_ok=True)
FRONTEND = BASE / 'frontend'
MAX_FILE_MB = int(os.getenv('MAX_FILE_MB', '25'))
JWT_SECRET = os.getenv('JWT_SECRET', 'change-me-in-production')
TOKEN_TTL_HOURS = int(os.getenv('TOKEN_TTL_HOURS', '168'))

app = FastAPI(title='Study With Me API', version='1.0.0')
security = HTTPBearer(auto_error=False)


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS users(
      id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
      password_hash TEXT, avatar TEXT, role TEXT DEFAULT 'Student', preferred_language TEXT DEFAULT 'English',
      response_style TEXT DEFAULT 'Medium', theme TEXT DEFAULT 'system', created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS documents(
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, filename TEXT NOT NULL,
      type TEXT NOT NULL, size INTEGER NOT NULL, page_count INTEGER DEFAULT 0, stored_path TEXT NOT NULL,
      extracted_text TEXT, uploaded_at TEXT NOT NULL, status TEXT DEFAULT 'ready',
      FOREIGN KEY(user_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS generations(
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, document_id INTEGER,
      generation_type TEXT NOT NULL, language TEXT, response_style TEXT, content TEXT NOT NULL,
      created_at TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS quizzes(
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, source_id INTEGER,
      questions TEXT NOT NULL, score INTEGER DEFAULT 0, created_at TEXT NOT NULL,
      FOREIGN KEY(user_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS flashcards(
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, source_id INTEGER,
      cards TEXT NOT NULL, created_at TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS history(
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, item_type TEXT NOT NULL,
      title TEXT NOT NULL, source_id INTEGER, created_at TEXT NOT NULL, is_saved INTEGER DEFAULT 0,
      is_pinned INTEGER DEFAULT 0, content TEXT, FOREIGN KEY(user_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS library(
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, title TEXT NOT NULL,
      category TEXT DEFAULT 'Study', item_type TEXT NOT NULL, content TEXT NOT NULL,
      created_at TEXT NOT NULL, is_favorite INTEGER DEFAULT 0, is_pinned INTEGER DEFAULT 0,
      FOREIGN KEY(user_id) REFERENCES users(id)
    );
    ''')
    conn.commit(); conn.close()

init_db()


def now(): return datetime.now(timezone.utc).isoformat()

def hash_password(p):
    salt = secrets.token_hex(16); digest = hashlib.pbkdf2_hmac('sha256', p.encode(), salt.encode(), 180000).hex()
    return f'{salt}${digest}'

def verify_password(p, stored):
    try:
        salt, digest = stored.split('$', 1)
        check = hashlib.pbkdf2_hmac('sha256', p.encode(), salt.encode(), 180000).hex()
        return secrets.compare_digest(check, digest)
    except Exception: return False

def make_token(user_id):
    # Compact signed token without external dependency: payload.signature
    exp = int((datetime.now(timezone.utc)+timedelta(hours=TOKEN_TTL_HOURS)).timestamp())
    payload = f'{user_id}.{exp}'
    sig = hashlib.sha256((payload+JWT_SECRET).encode()).hexdigest()
    return f'{payload}.{sig}'

def current_user(creds: HTTPAuthorizationCredentials = Depends(security)):
    if not creds: raise HTTPException(401, 'Please log in to continue.')
    try:
        uid, exp, sig = creds.credentials.split('.')
        expected = hashlib.sha256((f'{uid}.{exp}'+JWT_SECRET).encode()).hexdigest()
        if not secrets.compare_digest(sig, expected) or int(exp) < int(datetime.now(timezone.utc).timestamp()): raise ValueError()
        conn=db(); user=conn.execute('SELECT * FROM users WHERE id=?',(int(uid),)).fetchone(); conn.close()
        if not user: raise ValueError()
        return dict(user)
    except Exception: raise HTTPException(401, 'Your session is invalid or expired.')

class RegisterIn(BaseModel):
    name: str; email: EmailStr; password: str; role: str='Student'; language: str='English'
class LoginIn(BaseModel): email: EmailStr; password: str; remember: bool=True
class ProfileIn(BaseModel):
    name: Optional[str]=None; role: Optional[str]=None; language: Optional[str]=None; response_style: Optional[str]=None; theme: Optional[str]=None
class ChatIn(BaseModel):
    message: str; document_id: Optional[int]=None; image_data_url: Optional[str]=None; language: str='English'; response_style: str='Medium'; context: Optional[str]=None
class GenerateIn(BaseModel):
    document_id: Optional[int]=None; source_text: Optional[str]=None; generation_type: str; language: str='English'; response_style: str='Medium'; custom_request: Optional[str]=None
class DictIn(BaseModel): word: str; target_language: str='English'
class YoutubeIn(BaseModel): url: str
class LibraryIn(BaseModel): title: str; category: str='Study'; item_type: str='note'; content: str
class QuizScoreIn(BaseModel): score: int

@app.get('/api/health')
def health():
    return {'ok':True, 'ai_configured': AIService().configured, 'max_file_mb': MAX_FILE_MB}

@app.post('/api/auth/register')
def register(data:RegisterIn):
    if len(data.password)<8: raise HTTPException(400,'Password must be at least 8 characters.')
    conn=db()
    try:
        cur=conn.execute('INSERT INTO users(name,email,password_hash,role,preferred_language,created_at) VALUES(?,?,?,?,?,?)',
            (data.name.strip(),str(data.email).lower(),hash_password(data.password),data.role,data.language,now()))
        conn.commit(); uid=cur.lastrowid
    except sqlite3.IntegrityError: conn.close(); raise HTTPException(409,'An account with this email already exists.')
    conn.close(); return {'token':make_token(uid),'user':get_user(uid)}

@app.post('/api/auth/login')
def login(data:LoginIn):
    conn=db(); u=conn.execute('SELECT * FROM users WHERE email=?',(str(data.email).lower(),)).fetchone(); conn.close()
    if not u or not u['password_hash'] or not verify_password(data.password,u['password_hash']): raise HTTPException(401,'Incorrect email or password.')
    return {'token':make_token(u['id']),'user':dict(u)}

@app.post('/api/auth/logout')
def logout(): return {'ok':True}

@app.get('/api/auth/me')
def me(user=Depends(current_user)): return {'user':user}

def get_user(uid):
    conn=db(); u=conn.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone(); conn.close(); return dict(u)

@app.patch('/api/profile')
def profile(data:ProfileIn,user=Depends(current_user)):
    fields=[]; vals=[]
    for key, val in [('name',data.name),('role',data.role),('preferred_language',data.language),('response_style',data.response_style),('theme',data.theme)]:
        if val is not None: fields.append(f'{key}=?'); vals.append(val)
    if fields:
        vals.append(user['id']); conn=db(); conn.execute(f'UPDATE users SET {", ".join(fields)} WHERE id=?',vals); conn.commit(); conn.close()
    return {'user':get_user(user['id'])}

@app.post('/api/upload')
async def upload(file:UploadFile=File(...), user=Depends(current_user)):
    allowed={'application/pdf':'pdf','text/plain':'txt','application/vnd.openxmlformats-officedocument.wordprocessingml.document':'docx'}
    ext=Path(file.filename or '').suffix.lower()
    kind=allowed.get(file.content_type) or {'.pdf':'pdf','.txt':'txt','.docx':'docx'}.get(ext)
    if not kind: raise HTTPException(400,'Unsupported file. Please upload PDF, TXT, or DOCX.')
    data=await file.read()
    if len(data)>MAX_FILE_MB*1024*1024: raise HTTPException(413,f'Your file is too large. Maximum size is {MAX_FILE_MB} MB.')
    safe=re.sub(r'[^A-Za-z0-9._-]','_',file.filename or f'upload.{kind}')
    path=UPLOAD_DIR/f'{user["id"]}_{secrets.token_hex(8)}_{safe}'; path.write_bytes(data)
    try: text,pages=extract_document(path,kind)
    except Exception as e: path.unlink(missing_ok=True); raise HTTPException(400,'We could not read this document. Please check the file and try again.')
    conn=db(); cur=conn.execute('INSERT INTO documents(user_id,filename,type,size,page_count,stored_path,extracted_text,uploaded_at,status) VALUES(?,?,?,?,?,?,?,?,?)',
      (user['id'],file.filename,kind,len(data),pages,str(path),text,now(),'ready')); conn.commit(); did=cur.lastrowid
    conn.execute('INSERT INTO history(user_id,item_type,title,source_id,created_at,content) VALUES(?,?,?,?,?,?)',(user['id'],'PDF' if kind=='pdf' else kind.upper(),file.filename,did,now(),'')); conn.commit(); conn.close()
    return {'id':did,'filename':file.filename,'type':kind,'size':len(data),'page_count':pages,'status':'ready','text_preview':text[:500]}

@app.get('/api/documents')
def documents(user=Depends(current_user)):
    conn=db(); rows=conn.execute('SELECT id,filename,type,size,page_count,uploaded_at,status FROM documents WHERE user_id=? ORDER BY uploaded_at DESC',(user['id'],)).fetchall(); conn.close(); return {'items':[dict(x) for x in rows]}

def document_for(uid,did):
    conn=db(); d=conn.execute('SELECT * FROM documents WHERE id=? AND user_id=?',(did,uid)).fetchone(); conn.close()
    if not d: raise HTTPException(404,'Document not found.')
    return dict(d)

@app.post('/api/generate')
def generate(data:GenerateIn,user=Depends(current_user)):
    text=data.source_text or ''
    if data.document_id: text=document_for(user['id'],data.document_id)['extracted_text'] or ''
    if not text.strip(): raise HTTPException(400,'No source content is available.')
    try:
        result=AIService().generate(text, data.generation_type, data.language, data.response_style, data.custom_request)
    except AIConfigError as e: raise HTTPException(503,str(e))
    except AIServiceError: raise HTTPException(502,'AI service is temporarily unavailable. Please try again.')
    conn=db(); cur=conn.execute('INSERT INTO generations(user_id,document_id,generation_type,language,response_style,content,created_at) VALUES(?,?,?,?,?,?,?)',
      (user['id'],data.document_id,data.generation_type,data.language,data.response_style,result,now())); gid=cur.lastrowid
    title=data.generation_type.replace('_',' ').title(); source=data.document_id
    conn.execute('INSERT INTO history(user_id,item_type,title,source_id,created_at,content) VALUES(?,?,?,?,?,?)',(user['id'],data.generation_type,title,source,now(),result)); conn.commit(); conn.close()
    return {'id':gid,'title':title,'content':result,'language':data.language,'created_at':now()}

@app.post('/api/chat')
def chat(data:ChatIn,user=Depends(current_user)):
    source=''
    if data.document_id: source=document_for(user['id'],data.document_id)['extracted_text'] or ''
    if data.context: source += '\n\nPrevious context:\n'+data.context
    try: result=AIService().chat(data.message,source,data.language,data.response_style,data.image_data_url)
    except AIConfigError as e: raise HTTPException(503,str(e))
    except AIServiceError: raise HTTPException(502,'AI service is temporarily unavailable. Please try again.')
    conn=db(); conn.execute('INSERT INTO history(user_id,item_type,title,created_at,content) VALUES(?,?,?,?,?)',(user['id'],'Chat',data.message[:80],now(),result)); conn.commit(); conn.close()
    return {'content':result}

@app.post('/api/image/analyze')
async def image_analyze(file:UploadFile=File(...), prompt:str=Form('Explain this'), language:str=Form('English'), response_style:str=Form('Medium'), user=Depends(current_user)):
    data=await file.read()
    if len(data)>MAX_FILE_MB*1024*1024: raise HTTPException(413,f'Your file is too large. Maximum size is {MAX_FILE_MB} MB.')
    if not (file.content_type or '').startswith('image/'): raise HTTPException(400,'Please upload an image file.')
    data_url=image_to_data_url(data,file.content_type)
    try: result=AIService().chat(prompt,'',language,response_style,data_url)
    except AIConfigError as e: raise HTTPException(503,str(e))
    except AIServiceError: raise HTTPException(502,'AI service is temporarily unavailable. Please try again.')
    conn=db(); conn.execute('INSERT INTO history(user_id,item_type,title,created_at,content) VALUES(?,?,?,?,?)',(user['id'],'Image',file.filename or 'Image analysis',now(),result)); conn.commit(); conn.close()
    return {'content':result,'filename':file.filename}

@app.post('/api/youtube')
def youtube(data:YoutubeIn,user=Depends(current_user)):
    try: text,title=extract_youtube_transcript(data.url)
    except ValueError as e: raise HTTPException(400,str(e))
    if not text: raise HTTPException(422,"We couldn't access a transcript for this video. Transcript-based processing requires available captions/transcript or another supported extraction method.")
    return {'title':title,'transcript':text[:120000]}

@app.post('/api/dictionary')
def dictionary(data:DictIn,user=Depends(current_user)):
    prompt=f"Give a dictionary entry for the word '{data.word}'. Target language: {data.target_language}. Include meaning, simple meaning, pronunciation, part of speech, example sentence, synonyms, antonyms, translation, and easy explanation."
    try: result=AIService().chat(prompt,'',data.target_language,'Medium')
    except AIConfigError as e: raise HTTPException(503,str(e))
    except AIServiceError: raise HTTPException(502,'AI service is temporarily unavailable. Please try again.')
    conn=db(); conn.execute('INSERT INTO history(user_id,item_type,title,created_at,content) VALUES(?,?,?,?,?)',(user['id'],'Dictionary',data.word,now(),result)); conn.commit(); conn.close(); return {'content':result}

@app.get('/api/history')
def history(q:str='',item_type:str='',user=Depends(current_user)):
    conn=db(); sql='SELECT * FROM history WHERE user_id=?'; vals=[user['id']]
    if q: sql+=' AND (title LIKE ? OR content LIKE ?)'; vals += [f'%{q}%',f'%{q}%']
    if item_type: sql+=' AND item_type=?'; vals.append(item_type)
    sql+=' ORDER BY created_at DESC LIMIT 200'; rows=conn.execute(sql,vals).fetchall(); conn.close(); return {'items':[dict(x) for x in rows]}

@app.delete('/api/history/{hid}')
def delete_history(hid:int,user=Depends(current_user)):
    conn=db(); conn.execute('DELETE FROM history WHERE id=? AND user_id=?',(hid,user['id'])); conn.commit(); conn.close(); return {'ok':True}

@app.post('/api/library')
def save_library(data:LibraryIn,user=Depends(current_user)):
    conn=db(); cur=conn.execute('INSERT INTO library(user_id,title,category,item_type,content,created_at) VALUES(?,?,?,?,?,?)',(user['id'],data.title,data.category,data.item_type,data.content,now())); conn.commit(); lid=cur.lastrowid; conn.close(); return {'id':lid}

@app.get('/api/library')
def library(user=Depends(current_user)):
    conn=db(); rows=conn.execute('SELECT * FROM library WHERE user_id=? ORDER BY created_at DESC',(user['id'],)).fetchall(); conn.close(); return {'items':[dict(x) for x in rows]}

@app.delete('/api/library/{lid}')
def delete_library(lid:int,user=Depends(current_user)):
    conn=db(); conn.execute('DELETE FROM library WHERE id=? AND user_id=?',(lid,user['id'])); conn.commit(); conn.close(); return {'ok':True}


@app.post('/api/quiz/generate')
def quiz_generate(data:GenerateIn,user=Depends(current_user)):
    text=data.source_text or ''

    if data.document_id:
        doc=document_for(user['id'],data.document_id)
        if not doc:
            raise HTTPException(404,'Document not found.')
        text=doc['extracted_text'] or ''

    if not text.strip():
        raise HTTPException(400,'No source content is available.')

    # Keep source manageable for llama3.2:3b
    source=text[:30000]

    prompt=f"""Create exactly 10 multiple-choice questions from the supplied source.

Return ONLY a JSON object.
Do NOT write any text before or after the JSON.
Do NOT use Markdown.

Required format:

{{
  "questions": [
    {{
      "question": "Question text",
      "options": [
        "Option A",
        "Option B",
        "Option C",
        "Option D"
      ],
      "answer": 0,
      "explanation": "Short explanation",
      "difficulty": "Easy"
    }}
  ]
}}

Rules:
- Each question must have exactly 4 options.
- "answer" must be a number from 0 to 3.
- "difficulty" must be exactly Easy, Medium, or Hard.
- Every question must have a non-empty explanation.
- Use only information supported by the source.
- Language: {data.language}
"""

    try:
        raw=AIService().chat(
            prompt,
            source,
            data.language,
            data.response_style
        )
    except AIConfigError as e:
        raise HTTPException(503,str(e))
    except AIServiceError as e:
        print("QUIZ AI ERROR:",str(e))
        raise HTTPException(
            502,
            'AI service is temporarily unavailable. Please try again.'
        )

    try:
        clean=raw.strip()

        if '```' in clean:
            clean=clean.replace('```json','').replace('```JSON','').replace('```','').strip()

        start=clean.find('{')
        end=clean.rfind('}')

        if start == -1 or end == -1 or end <= start:
            raise ValueError('No JSON object found.')

        clean=clean[start:end+1]

        obj=json.loads(clean)

        questions=obj.get('questions',[])

        if not isinstance(questions,list) or not questions:
            raise ValueError('questions is empty.')

        valid_questions=[]

        for q in questions:

            if not isinstance(q,dict):
                continue

            question=str(q.get('question','')).strip()
            options=q.get('options',[])
            answer=q.get('answer',0)
            explanation=str(q.get('explanation','')).strip()
            difficulty=str(q.get('difficulty','Medium')).strip()

            if not question:
                continue

            if not isinstance(options,list) or len(options) != 4:
                continue

            options=[
                str(option).strip()
                for option in options
            ]

            if any(not option for option in options):
                continue

            try:
                answer=int(answer)
            except:
                continue

            if answer < 0 or answer > 3:
                continue

            if difficulty not in ['Easy','Medium','Hard']:
                difficulty='Medium'

            if not explanation:
                explanation='Based on the supplied source.'

            valid_questions.append({
                'question':question,
                'options':options,
                'answer':answer,
                'explanation':explanation,
                'difficulty':difficulty
            })

        if not valid_questions:
            raise ValueError('No valid questions.')

        questions=valid_questions[:10]

    except Exception as e:
        print("QUIZ FORMAT ERROR:",str(e))
        print("RAW AI RESPONSE:",raw[:5000])

        raise HTTPException(
            502,
            'The AI returned an invalid quiz format. Please retry.'
        )

    conn=db()

    cur=conn.execute(
        'INSERT INTO quizzes(user_id,source_id,questions,created_at) VALUES(?,?,?,?)',
        (
            user['id'],
            data.document_id,
            json.dumps(questions),
            now()
        )
    )

    qid=cur.lastrowid

    conn.execute(
        'INSERT INTO history(user_id,item_type,title,source_id,created_at,content) VALUES(?,?,?,?,?,?)',
        (
            user['id'],
            'Quiz',
            'AI Quiz',
            data.document_id,
            now(),
            json.dumps(questions)
        )
    )

    conn.commit()

    conn.close()

    return {
        'id':qid,
        'questions':questions
    }

@app.post('/api/flashcards/generate')
def flashcards_generate(data:GenerateIn,user=Depends(current_user)):
    text=data.source_text or ''

    if data.document_id:
        doc=document_for(user['id'],data.document_id)
        if not doc:
            raise HTTPException(404,'Document not found.')
        text=doc['extracted_text'] or ''

    if not text.strip():
        raise HTTPException(400,'No source content is available.')

    # Keep the prompt/source smaller for llama3.2:3b.
    # Very large PDF text can cause Ollama context errors.
    source=text[:30000]

    prompt="""Create exactly 12 useful flashcards from the supplied source.

Return ONLY a JSON object.
Do NOT write explanations before or after the JSON.
Do NOT use Markdown.

Required format:
{
  "cards": [
    {
      "front": "question or term",
      "back": "answer"
    }
  ]
}

Every card must contain a non-empty "front" and non-empty "back".
Use only information supported by the source."""

    try:
        raw=AIService().chat(
            prompt,
            source,
            data.language,
            data.response_style
        )
    except AIConfigError as e:
        raise HTTPException(503,str(e))
    except AIServiceError as e:
        print("FLASHCARD AI ERROR:",str(e))
        raise HTTPException(
            502,
            'AI service is temporarily unavailable. Please try again.'
        )

    # More tolerant JSON extraction
    try:
        clean=raw.strip()

        if '```' in clean:
            clean=clean.replace('```json','').replace('```JSON','').replace('```','').strip()

        start=clean.find('{')
        end=clean.rfind('}')

        if start == -1 or end == -1 or end <= start:
            raise ValueError('No JSON object found.')

        clean=clean[start:end+1]

        obj=json.loads(clean)
        cards=obj.get('cards',[])

        if not isinstance(cards,list) or not cards:
            raise ValueError('cards is empty.')

        valid_cards=[]

        for card in cards:
            if not isinstance(card,dict):
                continue

            front=str(card.get('front','')).strip()
            back=str(card.get('back','')).strip()

            if front and back:
                valid_cards.append({
                    'front':front,
                    'back':back
                })

        if not valid_cards:
            raise ValueError('No valid cards.')

        cards=valid_cards[:12]

    except Exception as e:
        print("FLASHCARD FORMAT ERROR:",str(e))
        print("RAW AI RESPONSE:",raw[:5000])

        raise HTTPException(
            502,
            'The AI returned an invalid flashcard format. Please retry.'
        )

    conn=db()

    cur=conn.execute(
        'INSERT INTO flashcards(user_id,source_id,cards,created_at) VALUES(?,?,?,?)',
        (
            user['id'],
            data.document_id,
            json.dumps(cards),
            now()
        )
    )

    conn.execute(
        'INSERT INTO history(user_id,item_type,title,source_id,created_at,content) VALUES(?,?,?,?,?,?)',
        (
            user['id'],
            'Flashcards',
            'AI Flashcards',
            data.document_id,
            now(),
            json.dumps(cards)
        )
    )

    conn.commit()

    fid=cur.lastrowid

    conn.close()

    return {
        'id':fid,
        'cards':cards
    }
@app.post('/api/quiz/score/{qid}')
def quiz_score(qid:int,data:QuizScoreIn,user=Depends(current_user)):
    conn=db(); conn.execute('UPDATE quizzes SET score=? WHERE id=? AND user_id=?',(data.score,qid,user['id'])); conn.commit(); conn.close(); return {'ok':True}

@app.get('/api/stats')
def stats(user=Depends(current_user)):
    conn=db();
    docs=conn.execute('SELECT COUNT(*) c FROM documents WHERE user_id=?',(user['id'],)).fetchone()['c']
    gens=conn.execute('SELECT COUNT(*) c FROM generations WHERE user_id=?',(user['id'],)).fetchone()['c']
    hist=conn.execute('SELECT COUNT(*) c FROM history WHERE user_id=?',(user['id'],)).fetchone()['c']
    lib=conn.execute('SELECT COUNT(*) c FROM library WHERE user_id=?',(user['id'],)).fetchone()['c']
    conn.close(); return {'documents':docs,'generations':gens,'history':hist,'library':lib}

# Serve the single-page frontend after API routes.
app.mount('/assets', StaticFiles(directory=FRONTEND), name='assets')
@app.get('/{path:path}')
def spa(path:str):
    return FileResponse(FRONTEND/'index.html')
