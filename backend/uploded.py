from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from openai import OpenAI
import os
import tempfile
from pydantic import BaseModel
from analyze_answer import analyze_answer
import shutil
from datetime import datetime
from typing import List, Dict, Optional
import json
import uuid
from dotenv import load_dotenv
import PyPDF2
from docx import Document
import io
import subprocess
import tempfile
from openai import OpenAI
import requests
from pydantic import BaseModel
from database import conn, cursor
from datetime import datetime


load_dotenv()

# Configuration
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

from fastapi.staticfiles import StaticFiles

app = FastAPI()

# Mount uploads folder to serve files
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")


# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Allow all origins for Vercel deployment
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory storage (replace with database in production)
interviews = {}

def get_client():
    load_dotenv()
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        print("⚠️ Warning: OPENROUTER_API_KEY not found in environment")
    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key
    )

def get_or_create_candidate(name: str) -> int:
    cursor.execute("SELECT id FROM candidates WHERE name = ?", (name,))
    row = cursor.fetchone()

    if row:
        return row[0]

    cursor.execute(
        "INSERT INTO candidates (name, created_at) VALUES (?, ?)",
        (name, datetime.now().isoformat())
    )
    conn.commit()
    return cursor.lastrowid


def extract_skills(text: str) -> List[str]:
    """Extract skills from resume text."""
    skills = []
    common_skills = [
        # Programming Languages
        "Python", "JavaScript", "Java", "C++", "C#", "PHP", "Ruby", "Swift", "Kotlin", "Go", "Rust", "TypeScript",
        # Web Technologies
        "HTML", "CSS", "React", "Angular", "Vue.js", "Node.js", "Django", "Flask", "Spring", "ASP.NET", "Express.js",
        # Databases
        "SQL", "MySQL", "PostgreSQL", "MongoDB", "Oracle", "SQLite", "Redis", "Cassandra",
        # Cloud & DevOps
        "AWS", "Azure", "Google Cloud", "Docker", "Kubernetes", "Terraform", "Ansible", "Jenkins", "Git", "CI/CD",
        # Data Science
        "Machine Learning", "Deep Learning", "Data Analysis", "Pandas", "NumPy", "TensorFlow", "PyTorch", "scikit-learn",
        # Other
        "REST API", "GraphQL", "Microservices", "Agile", "Scrum", "TDD", "OOP", "Functional Programming"
    ]
    
    for skill in common_skills:
        if skill.lower() in text.lower():
            skills.append(skill)
    
    return list(dict.fromkeys(skills))[:8]  # Remove duplicates and limit to 8 skills

def analyze_resume_or_jd(text: str):
    prompt = f"""
    Analyze the following resume or job description and return STRICT JSON only:
    {{
      "skills": [],
      "projects": [],
      "tools_and_technologies": [],
      "experience_level": "",
      "domains": [],
      "important_keywords": []
    }}
    Content: {text}
    """

    try:
        response = get_client().chat.completions.create(
            model="google/gemini-2.0-flash-001", # OpenRouter model ID
            messages=[{"role": "user", "content": prompt}]
        )
        
        raw_text = response.choices[0].message.content
        # Extract JSON
        json_start = raw_text.find("{")
        json_end = raw_text.rfind("}") + 1
        return json.loads(raw_text[json_start:json_end])
    except Exception as e:
        print(f"OpenRouter Analysis Error: {e}")
        return {"skills": [], "projects": [], "tools_and_technologies": [], "experience_level": "Unknown", "domains": [], "important_keywords": []}
    
def extract_experiences(text: str) -> List[Dict]:
    """Extract work experiences from resume text."""
    experiences = []
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    
    for i, line in enumerate(lines):
        line_lower = line.lower()
        if any(role in line_lower for role in ['developer', 'engineer', 'analyst', 'specialist', 'manager', 'designer', 'researcher']):
            exp = {
                "title": line,
                "company": lines[i+1] if i+1 < len(lines) and len(lines[i+1]) < 50 else "a company"
            }
            # Avoid adding duplicate experiences
            if not any(e['title'] == exp['title'] and e['company'] == exp['company'] for e in experiences):
                experiences.append(exp)
                if len(experiences) >= 3:  # Limit to 3 experiences
                    break
    
    return experiences

def extract_projects(text: str) -> List[Dict]:
    """Extract projects from resume text."""
    projects = []
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    
    for i, line in enumerate(lines):
        line_lower = line.lower()
        if ("project" in line_lower or "portfolio" in line_lower) and len(line.split()) < 5:
            project = {
                "name": line.replace("Project:", "").replace("project:", "").strip(),
                "description": lines[i+1] if i+1 < len(lines) and 10 < len(lines[i+1]) < 200 else ""
            }
            # Avoid adding duplicate projects
            if not any(p['name'] == project['name'] for p in projects):
                projects.append(project)
    
    return projects

def generate_resume_questions(resume_text: str) -> List[Dict[str, str]]:
    """Generate personalized interview questions based on resume content."""
    print("Generating personalized resume-specific questions...")
    
    # Extract structured information
    skills = extract_skills(resume_text)
    experiences = extract_experiences(resume_text)
    projects = extract_projects(resume_text)
    
    questions = []
    
    # 1. Self Introduction (First 2 questions)
    intro_questions = [
        {
            "id": 1,
            "question": "Can you please introduce yourself and tell us about your professional background?",
            "difficulty": "Easy",
            "type": "Self-Introduction",
            "category": "Basic"
        },
        {
            "id": 2,
            "question": "What motivated you to pursue a career in this field, and what are your key strengths?",
            "difficulty": "Easy",
            "type": "Self-Introduction",
            "category": "Background"
        }
    ]
    questions.extend(intro_questions)
    
    # 2. Basic Skills Questions (Questions 3-4)
    if skills:
        # Take top 2 skills for basic questions
        for skill in skills[:2]:
            questions.append({
                "id": len(questions) + 1,
                "question": f"How would you rate your proficiency in {skill} and what projects have you used it in?",
                "difficulty": "Easy",
                "type": "Technical",
                "category": f"{skill} Basics"
            })
    
    # 3. Experience Questions (Middle Questions)
    for i, exp in enumerate(experiences[:2]):  # Limit to 2 experiences
        company = exp.get('company', 'your previous role')
        title = exp.get('title', '')
        
        questions.append({
            "id": len(questions) + 1,
            "question": f"At {company} as a {title}, what were your key responsibilities and achievements?",
            "difficulty": "Medium",
            "type": "Experience",
            "category": "Work History"
        })
        
        # Add a follow-up question about challenges
        if i == 0:  # Only add one challenge question
            questions.append({
                "id": len(questions) + 1,
                "question": f"What was the most challenging project you worked on at {company} and how did you handle it?",
                "difficulty": "Medium",
                "type": "Problem-Solving",
                "category": "Work Challenges"
            })
    
    # 4. Advanced Skills Questions (After Experience)
    if len(skills) > 2:  # If we have more than 2 skills
        for skill in skills[2:4]:  # Take next 2 skills for advanced questions
            questions.append({
                "id": len(questions) + 1,
                "question": f"Can you explain a complex problem you solved using {skill}? What was your approach and what did you learn?",
                "difficulty": "Hard",
                "type": "Technical",
                "category": f"Advanced {skill}"
            })
    
    # 5. Project Questions (If we need more questions)
    if len(questions) < 8 and projects:  # If we don't have enough questions yet
        for proj in projects[:1]:  # Limit to 1 project
            title = proj.get('title', 'a project')
            
            questions.append({
                "id": len(questions) + 1,
                "question": f"Tell me about your project '{title}'. What was your role, and what technologies did you use?",
                "difficulty": "Medium",
                "type": "Project",
                "category": "Projects"
            })
    
    # 6. Future and Closing Questions (Last 2 questions)
    future_questions = [
        {
            "question": "What technical skills are you currently working to improve, and how are you going about it?",
            "difficulty": "Easy",
            "type": "Career Development",
            "category": "Future Goals"
        },
        {
            "question": "Where do you see your career in the next 3-5 years, and how does this position align with your goals?",
            "difficulty": "Medium",
            "type": "Career Goals",
            "category": "Future Planning"
        }
    ]
    
    # Add future questions with proper IDs
    for q in future_questions:
        questions.append({
            "id": len(questions) + 1,
            **q
        })
    
    # Ensure we have at least 10 questions
    generic_questions = [
        "Can you describe a time when you had to work under pressure to meet a tight deadline?",
        "How do you approach learning new technologies or programming languages?",
        "Can you explain a technical concept to someone who doesn't have a technical background?",
        "What development tools and IDEs are you most comfortable using, and why?",
        "How do you handle code reviews and feedback on your work?",
        "What version control systems have you worked with, and what's your experience with them?",
        "Can you describe your experience with testing and quality assurance processes?",
        "How do you stay updated with the latest industry trends and technologies?",
        "What's your approach to debugging complex issues in your code?",
        "Can you describe a time when you had to collaborate with a difficult team member and how you handled it?"
    ]
    
    # Add generic questions if we don't have enough
    while len(questions) < 10 and generic_questions:
        questions.append({
            "id": len(questions) + 1,
            "question": generic_questions.pop(0),
            "difficulty": "Medium",
            "type": "General",
            "category": "Professional Development"
        })
    
    # Ensure we don't have too many questions
    if len(questions) > 25:
        questions = questions[:25]
    
    print(f"Generated {len(questions)} questions for the interview")
    return questions

def extract_text_from_file(file_content: bytes, filename: str) -> str:
    """Extract text content from different file types."""
    file_extension = filename.lower().split('.')[-1]

    try:
        if file_extension == 'pdf':
            # Extract text from PDF
            pdf_reader = PyPDF2.PdfReader(io.BytesIO(file_content))
            text = ""
            for page in pdf_reader.pages:
                text += page.extract_text() + "\n"
            return text.strip()

        elif file_extension in ['docx', 'doc']:
            # Extract text from DOCX
            doc = Document(io.BytesIO(file_content))
            text = ""
            for paragraph in doc.paragraphs:
                text += paragraph.text + "\n"
            return text.strip()

        elif file_extension == 'txt':
            # Handle plain text files
            return file_content.decode('utf-8')

        else:
            # Try to decode as UTF-8 text for other formats
            return file_content.decode('utf-8')

    except Exception as e:
        print(f"Error extracting text from {filename}: {e}")
        # Fallback: try to decode as UTF-8
        try:
            return file_content.decode('utf-8', errors='ignore')
        except:
            raise HTTPException(status_code=400, detail=f"Unable to process file {filename}. Supported formats: PDF, DOCX, TXT")

def generate_jd_questions(jd_text: str) -> List[Dict[str, str]]:
    """Generate interview questions based on Job Description using AI."""
    print("Generating questions from Job Description...")
    
    questions = [
        {
            "id": 1,
            "question": "Can you please introduce yourself and tell us why you are interested in this specific role?",
            "difficulty": "Easy",
            "type": "Self-Introduction",
            "category": "Basic"
        }
    ]

    prompt = f"""
    You are an expert technical recruiter constructing a rigorous interview.
    
    Job Description:
    {jd_text[:4000]}
    
    Task:
    1. EXTRACT top 5 critical technical keywords/skills from the Job Description (e.g., 'React', 'AWS', 'System Design').
    2. GENERATE 6 specific interview questions testing these exact skills.
       - The extracted keywords MUST be the focus of the questions.
       - Do NOT ask generic "soft skill" questions unless the JD emphasizes them.
       - Vary difficulty: Start with basic checks, move to scenario-based/hard problems.
    
    Return STRICT JSON format:
    {{
        "extracted_keywords": ["Skill1", "Skill2", ...],
        "questions": [
            {{
                "question": "Specific question testing a skill...",
                "difficulty": "Medium",
                "type": "Technical",
                "category": "Skill Name"
            }}
        ]
    }}
    """

    try:
        response = get_client().chat.completions.create(
            model="openai/gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}]
        )
        raw = response.choices[0].message.content
        start = raw.find("{")
        end = raw.rfind("}") + 1
        data = json.loads(raw[start:end])
        
        # Log extracted keywords for debugging/logging
        print(f"✅ Extracted JD Keywords: {data.get('extracted_keywords', [])}")
        
        # Add generated questions to the list
        for q in data.get("questions", []):
            questions.append({
                "id": len(questions) + 1,
                "question": q["question"],
                "difficulty": q.get("difficulty", "Medium"),
                "type": q.get("type", "General"),
                "category": q.get("category", "JD Requirement")
            })

            
    except Exception as e:
        print(f"Error generating JD questions: {e}")
        
        # --- OFFLINE/FALLBACK MODE ---
        # If API fails, try to extract keywords manually using Regex/List
        common_keywords = [
            "Python", "Java", "React", "Angular", "Vue", "AWS", "Azure", "Docker", "Kubernetes", "SQL", 
            "NoSQL", "Git", "CI/CD", "Machine Learning", "AI", "Data Science", "Spring", "Node.js", 
            "JavaScript", "TypeScript", "C++", "C#", ".NET", "Go", "Rust", "Swift", "Kotlin", "Flutter"
        ]
        
        found_keywords = []
        for kw in common_keywords:
            if kw.lower() in jd_text.lower():
                found_keywords.append(kw)
        
        print(f"⚠️ Offline Mode: Found keywords {found_keywords}")
        
        if found_keywords:
            for i, kw in enumerate(found_keywords[:5]): # Top 5 matched
                questions.append({
                    "id": len(questions) + 1,
                    "question": f"The job description mentions {kw}. Can you describe your experience with {kw} and a challenging problem you solved using it?",
                    "difficulty": "Medium",
                    "type": "Technical",
                    "category": f"{kw} Skill"
                })
        else:
             # Genuine Fallback if absolutely no keywords matched
             questions.extend([
                {
                    "id": 2,
                    "question": "What specifically attracted you to the technical requirements of this position?",
                    "difficulty": "Medium",
                    "type": "General",
                    "category": "Fit"
                },
                {
                    "id": 3,
                    "question": "Can you walk us through your most significant technical achievement relevant to this role?",
                    "difficulty": "Hard",
                    "type": "Project",
                    "category": "Experience"
                }
            ])

    return questions

def generate_mock_questions(text: str, source: str) -> List[Dict[str, str]]:
    """Generate mock interview questions."""
    if "resume" in source.lower():
        return generate_resume_questions(text)
    else:  # job description
        return generate_jd_questions(text)

def score_answer(question: str, answer: str):
    prompt = f"""
You are an interview evaluator.

Question:
{question}

Candidate Answer:
{answer}

Evaluate on:
1. Relevance
2. Clarity
3. Technical depth (if applicable)
4. Confidence

Return STRICT JSON only:
{{
  "score": 0-10,
  "feedback": "short constructive feedback",
  "keywords": ["keyword1", "keyword2"]
}}
"""

    response = get_client().chat.completions.create(
        model="openai/gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )

    raw = response.choices[0].message.content
    start = raw.find("{")
    end = raw.rfind("}") + 1
    return json.loads(raw[start:end])

# --- ADAPTIVE INTERVIEW LOGIC ---

class NextQuestionRequest(BaseModel):
    interview_id: str
    current_question_id: int
    answer_text: str

def generate_followup_question(answer_text: str, resume_context: str, current_q_id: int) -> Dict:
    prompt = f"""
    You are an intelligent technical interviewer.
    
    Context:
    - Candidate Resume Summary: {resume_context[:1000]}...
    - Candidate's Last Answer: "{answer_text}"
    
    Task:
    Generate ONE follow-up interview question (JSON) to dig deeper into what the candidate just said.
    - If they mentioned a Project, ask about architectural decisions or challenges in THAT project.
    - If they mentioned a specific Tech Stack (e.g., React, Python), ask a conceptual question about it.
    - If their answer was vague, ask them to clarify specific examples.
    
    Return STRICT JSON:
    {{
        "question": "The actual question string...",
        "difficulty": "Medium",
        "type": "Follow-up",
        "category": "Deep Dive"
    }}
    """
    
    try:
        response = get_client().chat.completions.create(
            model="openai/gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}]
        )
        raw = response.choices[0].message.content
        start = raw.find("{")
        end = raw.rfind("}") + 1
        q_data = json.loads(raw[start:end])
        
        # Add ID
        q_data["id"] = current_q_id + 1
        return q_data
    except Exception as e:
        print(f"Error generating follow-up: {e}")
        # Fallback
        return {
            "id": current_q_id + 1,
            "question": "Can you elaborate more on the technical challenges you faced in your recent projects?",
            "difficulty": "Medium",
            "type": "General",
            "category": "Follow-up"
        }

@app.post("/generate-next-question")
def api_gen_next_question(req: NextQuestionRequest):
    if req.interview_id not in interviews:
        raise HTTPException(status_code=404, detail="Interview not found")
        
    interview = interviews[req.interview_id]
    
    # Generate the question
    new_question = generate_followup_question(
        req.answer_text, 
        interview.get("profile_text", ""),
        req.current_question_id
    )
    
    # Insert this new question into the list right after current
    # Find current index
    current_idx = -1
    for i, q in enumerate(interview["questions"]):
        if int(q["id"]) == req.current_question_id:
            current_idx = i
            break
            
    if current_idx != -1:
        # Check if we already have a follow-up (avoid infinite expansion if re-running)
        if current_idx + 1 < len(interview["questions"]):
             # If next question is already a "Follow-up", maybe replace it? 
             # For now, let's just INSERT it to be dynamic.
             # Shift IDs of subsequent questions
             for q in interview["questions"][current_idx+1:]:
                 q["id"] = int(q["id"]) + 1
                 
        interview["questions"].insert(current_idx + 1, new_question)
        
        # Update DB with new question list
        cursor.execute("UPDATE interviews SET questions = ? WHERE id = ?", (json.dumps(interview["questions"]), req.interview_id))
        conn.commit()
        
        return new_question
    
    raise HTTPException(status_code=400, detail="Current question ID not found")


@app.post("/upload-resume")
@app.post("/upload-resume/")
async def upload_resume(
    file: UploadFile = File(...),
    source: str = Form("resume")
):
    try:
        print(f"Uploading resume with source: {source}")

        # Read file content
        content = await file.read()

        # Extract text based on file type
        content_str = extract_text_from_file(content, file.filename)

        if not content_str.strip():
            raise HTTPException(status_code=400, detail="No readable text found in the file")

        # Generate interview ID
        interview_id = f"int_{int(datetime.now().timestamp())}_{uuid.uuid4().hex[:8]}"

        # Analyze the resume
        profile_analysis = analyze_resume_or_jd(content_str)

        # Generate questions
        questions = generate_mock_questions(content_str, source)

        if not questions:
            raise HTTPException(status_code=400, detail="Failed to generate questions")

        # Store interview data (RAM)
        interviews[interview_id] = {
            "id": interview_id,
            "source": source,
            "profile_text": content_str[:5000], # Store more text
            "profile_analysis": profile_analysis,
            "questions": questions,
            "answers": {},
            "created_at": datetime.now().isoformat()
        }

        # Store interview data (DB)
        try:
            cursor.execute("""
                INSERT INTO interviews (id, source, profile_text, questions, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (
                interview_id, 
                source, 
                content_str[:5000], 
                json.dumps(questions), 
                datetime.now().isoformat()
            ))
            conn.commit()
        except Exception as db_e:
            print(f"⚠️ DB Save Error: {db_e}")


        return {
            "interview_id": interview_id,
            "total_questions": len(questions),
            "first_question": questions[0]
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"Upload error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to process resume: {str(e)}")

@app.post("/start-interview")
@app.post("/start-interview/")
async def start_interview(
    content: str = Form(...),
    source: str = Form("resume")
):
    try:
        print(f"Starting interview with source: {source}")

        interview_id = f"int_{int(datetime.now().timestamp())}_{uuid.uuid4().hex[:8]}"

        # ✅ STEP-3.2 → AI ANALYSIS (CORRECT PLACE)
        profile_analysis = analyze_resume_or_jd(content)

        # Generate questions based on Source (Resume vs JD)
        questions = generate_mock_questions(content, source)

        if not questions:
            raise HTTPException(status_code=400, detail="Failed to generate questions")

        # ✅ STEP-3.3 → STORE ANALYSIS HERE (RAM)
        interviews[interview_id] = {
            "id": interview_id,
            "source": source,
            "profile_text": content[:5000],
            "profile_analysis": profile_analysis,
            "questions": questions,
            "answers": {},
            "created_at": datetime.now().isoformat()
        }

        # Store interview data (DB)
        try:
            cursor.execute("""
                INSERT INTO interviews (id, source, profile_text, questions, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (
                interview_id, 
                source, 
                content[:5000], 
                json.dumps(questions), 
                datetime.now().isoformat()
            ))
            conn.commit()
        except Exception as db_e:
            print(f"⚠️ DB Save Error: {db_e}")

        return {
            "interview_id": interview_id,
            "total_questions": len(questions),
            "first_question": questions[0]
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/interview/{interview_id}/question/{question_id}")
async def get_question(interview_id: str, question_id: int):
    # Restore from DB if not in RAM
    if interview_id not in interviews:
        cursor.execute("SELECT source, profile_text, questions, created_at FROM interviews WHERE id = ?", (interview_id,))
        row = cursor.fetchone()
        if row:
            print(f"🔄 Restoring interview {interview_id} from DB...")
            try:
                loaded_questions = json.loads(row[2])
                interviews[interview_id] = {
                    "id": interview_id,
                    "source": row[0],
                    "profile_text": row[1],
                    "questions": loaded_questions,
                    "answers": {},
                    "created_at": row[3]
                }
            except Exception as e:
                print(f"Restore failed: {e}")
    
    if interview_id not in interviews:
        raise HTTPException(status_code=404, detail="Interview not found")
    
    interview = interviews[interview_id]
    # Ensure ID comparison works (cast both to int)
    question = next((q for q in interview["questions"] if int(q["id"]) == int(question_id)), None)
    
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
        
    return {
        "current_question": question,  # This key must match what your HTML looks for
        "total_questions": len(interview["questions"]),
        "interview_id": interview_id
    }
# Add this import at the top

import base64

@app.post("/upload-answer")
async def upload_answer(
    interview_id: str = Form(...),
    question_id: int = Form(...),
    video: UploadFile = File(...)
):
    if interview_id not in interviews:
        raise HTTPException(status_code=404, detail="Interview not found")

    with tempfile.TemporaryDirectory() as tmp:
        video_path = os.path.join(tmp, "input.webm")
        audio_path = os.path.join(tmp, "audio.wav")

        with open(video_path, "wb") as f:
            f.write(await video.read())

        # Extract audio using ffmpeg
        subprocess.run([
            "ffmpeg", "-i", video_path,
            "-ar", "16000",
            "-ac", "1",
            audio_path
        ], check=True)

        # Whisper STT

@app.get("/interview/{interview_id}/summary")
async def get_interview_summary(interview_id: str):
    """Get a summary of the interview including all questions and answers."""
    if interview_id not in interviews:
        raise HTTPException(status_code=404, detail="Interview not found")
    
    interview = interviews[interview_id]
    return {
        "interview_id": interview_id,
        "source": interview["source"],
        "created_at": interview["created_at"],
        "total_questions": len(interview["questions"]),
        "questions_answered": len(interview["answers"]),
        "questions": interview["questions"],
        "answers": interview["answers"]
    }
@app.get("/")
def root():
    return {"status": "Backend is running"}

class ChatRequest(BaseModel):
    message: str
@app.post("/chat")
def chat(req: ChatRequest):
    url = "https://openrouter.ai/api/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost",
        "X-Title": "Voice Chatbot"
    }

    data = {
        "model": "openai/gpt-4o-mini",
        "messages": [
            {
                "role": "system",
                "content": "You are a helpful interview assistant. Keep responses short."
            },
            {
                "role": "user",
                "content": req.message
            }
        ]
    }

    response = requests.post(url, headers=headers, json=data)

    return {
        "reply": response.json()["choices"][0]["message"]["content"]
    }

class AnswerRequest(BaseModel):
    interview_id: str
    candidate_name: str
    question_id: int
    question_text: str
    answer_text: str
    


@app.post("/save-answer")
async def save_answer(
    interview_id: str = Form(...),
    question_id: int = Form(...),
    question_text: str = Form(...),
    answer_text: str = Form(...),
    candidate_name: str = Form("Candidate")
):
    print(f"💾 Saving answer for {question_id}...")
    
    # Get context
    context = ""
    # Try RAM first
    if interview_id in interviews:
         profile_text = interviews[interview_id].get("profile_text", "")
         source = interviews[interview_id].get("source", "Resume")
         context = f"Candidate's {source}: {profile_text}"
    else:
        # Try DB
        try:
            cursor.execute("SELECT profile_text, source FROM interviews WHERE id = ?", (interview_id,))
            row = cursor.fetchone()
            if row:
                context = f"Candidate's {row[1]}: {row[0]}"
                # Optional: Restore to RAM for next time
                # interviews[interview_id] = { "profile_text": row[0], "source": row[1] } 
        except Exception as e:
            print(f"⚠️ Context fetch error: {e}")

    # Use the robust analyze_answer function
    ai_result = analyze_answer(question_text, answer_text, context)

    # Prepare keywords (handle list or string)
    keywords = ai_result.get("keywords", [])
    if isinstance(keywords, list):
        keywords_str = ",".join(keywords)
    else:
        keywords_str = str(keywords)

    cursor.execute("""
        INSERT INTO answers (
            interview_id,
            question_id,
            question_text,
            answer_text,
            ai_score,
            ai_feedback,
            ai_keywords,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        interview_id,
        question_id,
        question_text,
        answer_text,
        ai_result.get("overall_score", 0),
        ai_result.get("feedback", "No feedback"),
        keywords_str,
        datetime.now().isoformat()
    ))

    conn.commit()
    print("✅ Answer saved to DB.")

    return {
        "status": "saved",
        "ai_score": ai_result.get("overall_score", 0),
        "ai_feedback": ai_result.get("feedback", "")
    }

@app.get("/interview/{interview_id}/ai-summary")
def interview_ai_summary(interview_id: str):
    cursor.execute("""
        SELECT ai_score FROM answers
        WHERE interview_id = ? AND ai_score IS NOT NULL
    """, (interview_id,))
    
    scores = [row[0] for row in cursor.fetchall()]
    avg_score = round(sum(scores) / len(scores), 2) if scores else 0

    return {
        "interview_id": interview_id,
        "average_score": avg_score,
        "total_questions": len(scores)
    }

class AnalyzeRequest(BaseModel):
    interview_id: Optional[str] = None
    question_id: Optional[int] = None
    question: str
    answer: str

@app.post("/analyze-answer")
def analyze(req: AnalyzeRequest):
    context = ""
    # Retrieve Resume/JD context from the CURRENT in-memory session (not historical DB data)
    if req.interview_id and req.interview_id in interviews:
         profile_text = interviews[req.interview_id].get("profile_text", "")
         source = interviews[req.interview_id].get("source", "Resume")
         context = f"Candidate's {source}: {profile_text}"
    
    result = analyze_answer(req.question, req.answer, context)

    # Store in DB
    try:
        cursor.execute("""
            INSERT INTO answers (
                interview_id, question_id, question_text, answer_text, 
                ai_score, ai_feedback, ai_keywords, corrected_answer, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            req.interview_id,
            req.question_id,
            req.question,
            req.answer,
            result.get("overall_score", 0),
            result.get("feedback", ""),
            json.dumps(result.get("keywords", [])),
            result.get("corrected_answer", ""),
            datetime.now().isoformat()
        ))
        conn.commit()
    except Exception as e:
        print(f"⚠️ Failed to save answer to DB: {e}")

    return result

@app.post("/upload-full-recording")
async def upload_full_recording(
    interview_id: str = Form(...),
    file: UploadFile = File(...)
):
    try:
        # Create directory for recordings if it doesn't exist
        recordings_dir = os.path.join(UPLOAD_FOLDER, "recordings")
        os.makedirs(recordings_dir, exist_ok=True)
        
        # Generate filename
        filename = f"{interview_id}_full_recording.webm"
        file_path = os.path.join(recordings_dir, filename)
        
        # Save file
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        # Update database
        cursor.execute("""
            UPDATE interviews
            SET recording_path = ?
            WHERE id = ?
        """, (file_path, interview_id))
        conn.commit()
        
        return {"status": "success", "file_path": file_path}
    except Exception as e:
        print(f"Error saving full recording: {e}")
        raise HTTPException(status_code=500, detail=str(e))


from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

@app.get("/generate-report/{interview_id}")
def generate_report(interview_id: str):
    # Fetch interview data
    cursor.execute("SELECT source, created_at, profile_text FROM interviews WHERE id = ?", (interview_id,))
    interview_data = cursor.fetchone()
    if not interview_data:
        raise HTTPException(status_code=404, detail="Interview not found")
    
    source, date, profile_text = interview_data
    
    # Fetch Q&A data
    cursor.execute("""
        SELECT question_text, answer_text, ai_score, ai_feedback, corrected_answer 
        FROM answers 
        WHERE interview_id = ? 
        ORDER BY question_id ASC
    """, (interview_id,))
    answers = cursor.fetchall()
    
    # Generate PDF
    pdf_filename = f"Interview_Report_{interview_id}.pdf"
    file_path = os.path.join(UPLOAD_FOLDER, pdf_filename)
    
    doc = SimpleDocTemplate(file_path, pagesize=letter)
    styles = getSampleStyleSheet()
    story = []
    
    # Title
    title_style = styles['Title']
    story.append(Paragraph(f"Interview Report", title_style))
    story.append(Spacer(1, 12))
    
    # Meta Info
    normal_style = styles['Normal']
    story.append(Paragraph(f"<b>Interview ID:</b> {interview_id}", normal_style))
    story.append(Paragraph(f"<b>Date:</b> {date}", normal_style))
    story.append(Paragraph(f"<b>Source:</b> {source}", normal_style))
    story.append(Spacer(1, 12))
    
    # Calculate Average Score
    if answers:
        scores = [row[2] for row in answers if row[2] is not None]
        avg_score = sum(scores) / len(scores) if scores else 0
        
        # Color code overall score
        color = "green" if avg_score >= 60 else "orange" if avg_score >= 40 else "red"
        story.append(Paragraph(f"<b>Overall Score:</b> <font color='{color}' size='14'>{avg_score:.1f}/100</font>", normal_style))
    else:
        story.append(Paragraph("<b>Overall Score:</b> N/A", normal_style))
    
    story.append(Spacer(1, 20))
    
    # Q&A Details
    for i, row in enumerate(answers):
        q_text, a_text, score, feedback, verified_answer = row
        
        # Question Header
        story.append(Paragraph(f"<b>Q{i+1}: {q_text}</b>", styles['Heading3']))
        story.append(Spacer(1, 5))
        
        # Your Answer
        a_text_disp = a_text if a_text else "(No answer recorded)"
        story.append(Paragraph(f"<b>Your Answer:</b> {a_text_disp}", normal_style))
        story.append(Spacer(1, 5))
        
        # AI Feedback & Score
        score_str = f"{score}/100" if score is not None else "N/A"
        feedback_str = feedback if feedback else "No feedback provided."
        
        # Color score (Green > 60, Red < 60)
        score_color = "green" if (score and score >= 60) else "red"
        
        story.append(Paragraph(f"<b>Score:</b> <font color='{score_color}'><b>{score_str}</b></font>", normal_style))
        story.append(Paragraph(f"<b>Feedback:</b> {feedback_str}", normal_style))
        
        # Suggested Answer (if verified answer exists and is different/better)
        if verified_answer:
             story.append(Spacer(1, 5))
             story.append(Paragraph(f"<b>Suggested/Corrected Answer:</b>", normal_style))
             story.append(Paragraph(f"<i>{verified_answer}</i>", normal_style))
             
        story.append(Spacer(1, 15))
        story.append(Paragraph("<hr width='100%'/>", normal_style)) # Separator using simplified HR if supported or just lines
        # Reportlab doesn't support <hr> well in Paragraph, use drawing or character separator
        # story.append(Paragraph("_" * 80, normal_style)) 
        
        story.append(Spacer(1, 15))

    doc.build(story)
    
    return {"status": "success", "file_path": file_path, "download_url": f"http://127.0.0.1:8000/uploads/{pdf_filename}"}

if __name__ == "__main__":
    import uvicorn
    import socket

    HOST = "0.0.0.0"
    DEFAULT_PORT = int(os.getenv("PORT", 8000))

    def find_available_port(start_port: int, max_tries: int = 100) -> int:
        """Try to bind to ports starting at start_port and return the first available one."""
        for port in range(start_port, start_port + max_tries):
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                # Try binding to the candidate port to check availability
                s.bind((HOST, port))
                s.close()
                return port
            except OSError:
                s.close()
                continue
        raise RuntimeError(f"No available ports found in range {start_port}-{start_port + max_tries - 1}")

    port_to_use = find_available_port(DEFAULT_PORT)
    if port_to_use != DEFAULT_PORT:
        print(f"Port {DEFAULT_PORT} is in use; starting server on available port {port_to_use} instead.")

    uvicorn.run(app, host=HOST, port=port_to_use)