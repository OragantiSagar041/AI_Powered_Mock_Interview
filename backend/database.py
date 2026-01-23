import sqlite3

conn = sqlite3.connect("interviews.db", check_same_thread=False)
cursor = conn.cursor()

# Candidates
cursor.execute("""
CREATE TABLE IF NOT EXISTS candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE,
    created_at TEXT
)
""")

# Interviews
cursor.execute("""
CREATE TABLE IF NOT EXISTS interviews (
    id TEXT PRIMARY KEY,
    candidate_id INTEGER,
    source TEXT,
    created_at TEXT,
    FOREIGN KEY(candidate_id) REFERENCES candidates(id)
)
""")

# Answers (BASE TABLE)
cursor.execute("""
CREATE TABLE IF NOT EXISTS answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    interview_id TEXT,
    question_id INTEGER,
    question_text TEXT,
    answer_text TEXT,
    created_at TEXT,
    FOREIGN KEY(interview_id) REFERENCES interviews(id)
)
""")

# Admins
cursor.execute("""
CREATE TABLE IF NOT EXISTS admins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE,
    password TEXT,
    created_at TEXT
)
""")

# Pre-created Interview Sessions (for Admin generated links)
cursor.execute("""
CREATE TABLE IF NOT EXISTS interview_sessions (
    link_id TEXT PRIMARY KEY,
    candidate_name TEXT,
    resume_text TEXT,
    job_description TEXT,
    status TEXT DEFAULT 'pending',
    created_by INTEGER,
    created_at TEXT
)
""")

# 🔹 ADD AI COLUMNS (SAFE)
def add_column_if_not_exists(table, column, datatype):
    try:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {datatype}")
    except sqlite3.OperationalError:
        pass  # column already exists

add_column_if_not_exists("answers", "ai_score", "INTEGER")
add_column_if_not_exists("answers", "ai_feedback", "TEXT")
add_column_if_not_exists("answers", "ai_keywords", "TEXT")
add_column_if_not_exists("answers", "corrected_answer", "TEXT")
add_column_if_not_exists("interviews", "recording_path", "TEXT")
add_column_if_not_exists("interviews", "profile_text", "TEXT")
add_column_if_not_exists("interviews", "questions", "TEXT") # JSON string

conn.commit()
