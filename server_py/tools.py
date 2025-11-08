from typing import Dict, List, Any
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from langchain_core.runnables import RunnableLambda
import json
from datetime import datetime

# In-memory session storage
SESSIONS: Dict[str, Dict[str, Any]] = {}

@tool
def upsert_profile(session_id: str, patch: Dict[str, Any]) -> str:
    """Save/update user interests, goals, pace, challenges, preferred topics."""
    if session_id not in SESSIONS:
        SESSIONS[session_id] = {"profile": {}, "history": []}
    SESSIONS[session_id]["profile"] = {**SESSIONS[session_id].get("profile", {}), **patch}
    return json.dumps(SESSIONS[session_id]["profile"])

@tool
def get_profile(session_id: str) -> str:
    """Fetch the user's profile for personalization."""
    if session_id not in SESSIONS:
        SESSIONS[session_id] = {"profile": {}, "history": []}
    return json.dumps(SESSIONS[session_id].get("profile", {}))

@tool
def save_assessment(session_id: str, assessment: Dict[str, Any]) -> str:
    """Save the latest CEFR assessment for the session."""
    if session_id not in SESSIONS:
        SESSIONS[session_id] = {"profile": {}, "history": []}
    SESSIONS[session_id]["last_assessment"] = assessment
    return json.dumps(assessment)

@tool
def save_quiz_result(session_id: str, test_type: str, user_input: str, score: float, context: Dict[str, Any] = None) -> str:
    """Save quiz/test result. test_type: 'unit_completion' | 'keyword_match' | 'pronunciation' | 'podcast' | 'reading' | 'image_detection'.
    context: Optional dict with 'expected_answer', 'difficulty_level', 'raw_metrics' for LLM scoring."""
    if session_id not in SESSIONS:
        SESSIONS[session_id] = {"profile": {}, "history": [], "quiz_results": []}
    if "quiz_results" not in SESSIONS[session_id]:
        SESSIONS[session_id]["quiz_results"] = []
    
    result = {
        "test_type": test_type,
        "user_input": user_input,
        "score": score,
        "timestamp": datetime.now().isoformat()
    }
    if context:
        result["context"] = context
    SESSIONS[session_id]["quiz_results"].append(result)
    return json.dumps(result)

def get_session(session_id: str) -> Dict[str, Any]:
    """Get or create a session."""
    if session_id not in SESSIONS:
        SESSIONS[session_id] = {"profile": {}, "history": []}
    return SESSIONS[session_id]

