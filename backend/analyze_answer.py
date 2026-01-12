import os
import requests
import json

from dotenv import load_dotenv

load_dotenv()

def analyze_answer(question: str, answer: str, context: str = ""):
    # Short-circuit for empty/placeholder answers
    if not answer or not answer.strip() or answer.strip() in ["Transcribing...", "Your speech will appear here automatically..."]:
        return {
            "corrected_answer": "No answer provided.",
            "grammar_score": 0,
            "relevance_score": 0,
            "clarity_score": 0,
            "overall_score": 0,
            "feedback": "Please record your answer before analyzing."
        }

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return {
            "corrected_answer": "Error: Missing API Key",
            "overall_score": 0,
            "feedback": "Server configuration error: OpenRouter API Key is missing."
        }
    prompt = f"""
You are an expert interview coach and evaluator. Your task is to provide high-quality, personalized feedback to a candidate.

Context (Resume/Job Description):
{context}

Question: "{question}"
Candidate's Answer: "{answer}"

Instructions:
1. **Analyze with Context**: Use the provided Resume/Job Description context to evaluate if the answer is factual and relevant to *this specific candidate*.
2. **Corrected Answer**: Rewrite the candidate's answer to be clearer, more professional, and concise. 
   - If the candidate's answer is mostly correct, polish it to make it sound like a top-tier candidate's response while keeping their core ideas.
   - If the candidate's answer is incorrect or vague, provide a model answer that directly addresses the question.
   - The corrected answer should be "clear" and "according to the user answer" where possible (filling in gaps), or "according to the question" if the user missed the mark completely.

3. **Feedback**: Provide "genuine" and constructive feedback.
   - Avoid generic phrases like "Good job."
   - Specifically mention what they did well (e.g., "You correctly identified X...").
   - valid criticisms (e.g., "You missed the concept of Y..." or "Your delivery was a bit rambling...").
   - Offer actionable advice on how to improve.

4. **Scoring**: Rate the answer on a scale of 0-100.

5. **Keywords**: Extract 2-3 key technical concepts mentioned (or missing).

Return VALID JSON ONLY.

Format:
{{
  "corrected_answer": "Your improved or model answer here...",
  "grammar_score": 0,
  "relevance_score": 0,
  "clarity_score": 0,
  "overall_score": 0,
  "feedback": "Your genuine, specific feedback here...",
  "keywords": ["key1", "key2"]
}}
"""

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": "openai/gpt-4o-mini",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0
            },
            timeout=30
        )

        if response.status_code == 402:
            raise Exception("API Quota Exceeded (402)")
        
        if response.status_code != 200:
             raise Exception(f"API Error {response.status_code}")

        data = response.json()
        
        if "choices" not in data:
            raise Exception("Invalid API structure")

        content = data["choices"][0]["message"]["content"]
        
        start = content.find("{")
        end = content.rfind("}") + 1
        if start == -1 or end == 0:
             raise Exception("No JSON found")

        return json.loads(content[start:end])

    except Exception as e:
        print(f"⚠️ Analysis API Failed: {e}")
        # FALLBACK: Heuristic Scoring (Offline Mode)
        word_count = len(answer.split())
        score = min(max(word_count * 2, 40), 85)
        return {
            "corrected_answer": "Analysis unavailable (Offline Mode)",
            "overall_score": score,
            "feedback": f"⚠️ API Quota/Error (Offline Mode). Your answer was recorded ({word_count} words). To get real AI analysis, check API credits.",
            "keywords": ["Offline"]
        }

print("✅ evaluate_answer.py loaded")
