"""Shared utilities for quiz generators."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import CONFIG
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from .cefr_utils import format_cefr_for_prompt

def get_llm():
    """Initialize LLM based on provider configuration."""
    if CONFIG.PROVIDER == "google":
        return ChatGoogleGenerativeAI(
            model=CONFIG.GOOGLE_MODEL,
            temperature=0.7,
            google_api_key=CONFIG.GOOGLE_API_KEY
        )
    else:
        return ChatOpenAI(
            model=CONFIG.OPENAI_MODEL,
            temperature=0.7,
            openai_api_key=CONFIG.OPENAI_API_KEY
        )

def normalize_cefr_level(level_input: str) -> str:
    """
    Normalize language level input to CEFR format.
    Converts "beginner", "intermediate", "advanced" or variations to A1, A2, B1, B2, C1, C2.
    Returns the normalized level or "A1" as default.
    """
    if not level_input:
        return "A1"
    
    level_lower = level_input.lower().strip()
    
    # Direct CEFR level matches
    if level_lower in ["a1", "a2", "b1", "b2", "c1", "c2"]:
        return level_lower.upper()
    
    # Beginner variations
    if any(word in level_lower for word in ["beginner", "basico", "básico", "basic", "start", "just starting"]):
        return "A1"
    
    # Intermediate variations
    if any(word in level_lower for word in ["intermediate", "intermedio", "medio", "middle"]):
        return "B1"
    
    # Advanced variations
    if any(word in level_lower for word in ["advanced", "avanzado", "high", "fluent", "fluency"]):
        return "B2"
    
    # Expert/Native variations
    if any(word in level_lower for word in ["expert", "native", "proficient", "nativo"]):
        return "C1"
    
    # Default to A1 if unclear
    return "A1"

def get_target_language(profile: dict) -> str:
    """
    Get the target language from profile.
    Returns the language name (e.g., "Spanish", "French", "German").
    Raises ValueError if target_language is not set.
    """
    if not profile:
        raise ValueError("Profile is required to determine target language")
    
    target_language = profile.get("target_language")
    if not target_language:
        raise ValueError("target_language must be set in profile before generating quizzes")
    
    return target_language

def get_recent_quiz_content(quiz_results: list, test_type: str = None, last_n: int = 5) -> dict:
    """
    Extract recent quiz content to avoid repetition.
    Returns a dict with:
    - 'words': list of recent words (for image_detection, keyword_match)
    - 'answers': list of recent correct answers (for unit_completion, podcast, reading)
    - 'sentences': list of recent sentences (for pronunciation, unit_completion)
    
    Args:
        quiz_results: List of quiz result dicts
        test_type: Optional filter by test type
        last_n: Number of recent quizzes to check (default 5)
    """
    recent_content = {
        "words": [],
        "answers": [],
        "sentences": []
    }
    
    if not quiz_results:
        return recent_content
    
    # Get recent quizzes (last N)
    recent_quizzes = quiz_results[-last_n:] if len(quiz_results) > last_n else quiz_results
    
    # Filter by test_type if specified
    if test_type:
        recent_quizzes = [q for q in recent_quizzes if q.get("test_type") == test_type]
    
    for quiz in recent_quizzes:
        context = quiz.get("context", {})
        expected_answer = context.get("expected_answer", "")
        user_input = quiz.get("user_input", "")
        
        # Extract words for image_detection and keyword_match
        if quiz.get("test_type") == "image_detection":
            if expected_answer:
                # For image_detection, expected_answer is the word
                word = expected_answer.strip().lower()
                if word and word not in recent_content["words"]:
                    recent_content["words"].append(word)
        elif quiz.get("test_type") == "keyword_match":
            # For keyword_match, context might contain word pairs
            # Try to extract words from context or user_input
            context_data = context
            if isinstance(context_data, dict):
                # Check if there's a words list or pairs stored
                if "words" in context_data:
                    words_list = context_data["words"]
                    if isinstance(words_list, list):
                        for w in words_list:
                            if isinstance(w, str) and w.strip().lower() not in recent_content["words"]:
                                recent_content["words"].append(w.strip().lower())
                # Also check user_input which might contain matched words
                if user_input:
                    # User input might be JSON string with matches
                    try:
                        matches = json.loads(user_input) if isinstance(user_input, str) else user_input
                        if isinstance(matches, list):
                            for match in matches:
                                if isinstance(match, dict):
                                    # Extract target language word
                                    for key in match.keys():
                                        if key.endswith("_word") or key == "target_word":
                                            word = match[key]
                                            if isinstance(word, str) and word.strip().lower() not in recent_content["words"]:
                                                recent_content["words"].append(word.strip().lower())
                    except:
                        pass
        
        # Extract answers for unit_completion, podcast, reading
        if quiz.get("test_type") in ["unit_completion", "podcast", "reading"]:
            if expected_answer:
                answer = expected_answer.strip().lower()
                if answer and answer not in recent_content["answers"]:
                    recent_content["answers"].append(answer)
        
        # Extract sentences for pronunciation
        if quiz.get("test_type") == "pronunciation":
            if expected_answer:
                sentence = expected_answer.strip().lower()
                if sentence and sentence not in recent_content["sentences"]:
                    recent_content["sentences"].append(sentence)
    
    return recent_content

def get_user_level(profile: dict, quiz_results: list) -> str:
    """
    Get the user's language level, prioritizing stated level from profile.
    If stated level exists, use it (possibly adjusted slightly based on quiz results).
    If no stated level, estimate from quiz results.
    Returns normalized CEFR level (A1-A2-B1-B2-C1-C2).
    """
    # First priority: User's stated level from profile (support both language_level and spanish_level for backward compatibility)
    stated_level = profile.get("language_level") or profile.get("spanish_level") if profile else None
    if stated_level:
        # Normalize the stated level
        normalized_stated = normalize_cefr_level(stated_level)
        
        # If we have quiz results, we can adjust slightly (within one level)
        if quiz_results:
            avg_score = sum(qr.get("score", 0) for qr in quiz_results) / len(quiz_results)
            
            # Only adjust if quiz performance significantly differs from stated level
            # Map level to expected score range
            level_expectations = {
                "A1": (0.3, 0.6),
                "A2": (0.4, 0.7),
                "B1": (0.5, 0.8),
                "B2": (0.6, 0.9),
                "C1": (0.75, 0.95),
                "C2": (0.85, 1.0)
            }
            
            expected_range = level_expectations.get(normalized_stated, (0.3, 0.7))
            
            # If performance is significantly outside expected range, adjust slightly
            if avg_score < expected_range[0] - 0.2:
                # Performance much lower - step down one level
                level_order = ["A1", "A2", "B1", "B2", "C1", "C2"]
                current_idx = level_order.index(normalized_stated) if normalized_stated in level_order else 0
                if current_idx > 0:
                    return level_order[current_idx - 1]
            elif avg_score > expected_range[1] + 0.15:
                # Performance much higher - step up one level
                level_order = ["A1", "A2", "B1", "B2", "C1", "C2"]
                current_idx = level_order.index(normalized_stated) if normalized_stated in level_order else 0
                if current_idx < len(level_order) - 1:
                    return level_order[current_idx + 1]
        
        # Return stated level (possibly adjusted)
        return normalized_stated
    
    # Fallback: Estimate from quiz results
    if quiz_results:
        avg_score = sum(qr.get("score", 0) for qr in quiz_results) / len(quiz_results)
        if avg_score >= 0.9:
            return "C2"
        elif avg_score >= 0.85:
            return "C1"
        elif avg_score >= 0.7:
            return "B2"
        elif avg_score >= 0.6:
            return "B1"
        elif avg_score >= 0.5:
            return "A2"
        else:
            return "A1"
    
    # Default fallback
    return "A1"
