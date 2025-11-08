"""Keyword match quiz generator."""
from typing import Dict, Any
from langchain_core.messages import SystemMessage, HumanMessage
import json
import re
from .utils import get_llm, get_user_level
from .cefr_utils import format_cefr_for_prompt
from tools import get_profile, get_session

llm = get_llm()

async def generate_keyword_match(session_id: str) -> Dict[str, Any]:
    """
    Generate a keyword match quiz with 5 Spanish-English word pairs.
    Returns: {
        "pairs": [{"spanish": "...", "english": "..."}, ...],
        "difficulty": "A1|A2|B1|B2|C1|C2"
    }
    """
    session = get_session(session_id)
    
    # Get user profile for personalization
    profile_str = await get_profile.ainvoke({"session_id": session_id})
    try:
        profile = json.loads(profile_str)
    except:
        profile = {}
    
    # Get current CEFR level - prioritize user's stated level from profile
    quiz_results = session.get("quiz_results", [])
    current_level = get_user_level(profile, quiz_results)
    
    # Generate level slightly above (10% harder)
    level_map = {
        "A1": "A1-A2",
        "A2": "A2-B1",
        "B1": "B1-B2",
        "B2": "B2-C1",
        "C1": "C1-C2",
        "C2": "C2"
    }
    target_level = level_map.get(current_level, "A1-A2")
    
    # Build prompt for LLM
    interests = profile.get("interests", "")
    # Use interests for TOPIC only, NEVER use name/age in content
    
    # Get CEFR description for the target level
    cefr_info = format_cefr_for_prompt(target_level)
    
    prompt = f"""Generate 5 Spanish-English word pairs for a vocabulary matching exercise.

Student's CEFR Level:
{cefr_info}

Requirements:
- Choose vocabulary appropriate for the student's language abilities as described above
- If interests provided ({interests}), choose vocabulary related to that TOPIC/THEME (e.g., if "tennis", include tennis-related words)
- NEVER use the student's actual name, age, or personal details
- Generate exactly 5 pairs
- Each pair should be one Spanish word and its English translation
- Words should match the vocabulary level described above
- Mix different word types (nouns, verbs, adjectives, etc.)
- Personalize vocabulary to student interests when possible

Format your response EXACTLY like this:
WORD1_SPANISH: palabra en español
WORD1_ENGLISH: word in English

WORD2_SPANISH: palabra en español
WORD2_ENGLISH: word in English

(Continue for all 5 pairs)

Example for A1-A2:
WORD1_SPANISH: gato
WORD1_ENGLISH: cat

WORD2_SPANISH: cocinar
WORD2_ENGLISH: to cook

WORD3_SPANISH: grande
WORD3_ENGLISH: big

WORD4_SPANISH: mesa
WORD4_ENGLISH: table

WORD5_SPANISH: correr
WORD5_ENGLISH: to run

Generate 5 pairs now for {target_level} level:"""

    messages = [
        SystemMessage(content="You are a Spanish language teacher creating vocabulary matching exercises. Always respond in the exact format requested."),
        HumanMessage(content=prompt)
    ]
    
    response = await llm.ainvoke(messages)
    content = response.content
    
    # Parse the response
    pairs = []
    lines = content.split('\n')
    
    current_spanish = None
    for line in lines:
        line = line.strip()
        if line.startswith('WORD') and '_SPANISH:' in line:
            # Extract Spanish word
            parts = line.split(':', 1)
            if len(parts) == 2:
                current_spanish = parts[1].strip()
        elif line.startswith('WORD') and '_ENGLISH:' in line:
            # Extract English word
            parts = line.split(':', 1)
            if len(parts) == 2 and current_spanish:
                english = parts[1].strip()
                pairs.append({
                    "spanish": current_spanish,
                    "english": english
                })
                current_spanish = None
    
    # Fallback: try to parse if format is slightly different
    if len(pairs) < 5:
        # Try alternative parsing
        # Look for Spanish: English patterns
        alt_pairs = re.findall(r'(\w+)\s*:\s*(\w+)', content)
        for span, eng in alt_pairs[:5]:
            if len(pairs) < 5:
                pairs.append({"spanish": span.strip(), "english": eng.strip()})
    
    # Ensure we have 5 pairs
    if len(pairs) < 5:
        # Add some default pairs as fallback
        default_pairs = [
            {"spanish": "casa", "english": "house"},
            {"spanish": "perro", "english": "dog"},
            {"spanish": "agua", "english": "water"},
            {"spanish": "libro", "english": "book"},
            {"spanish": "mesa", "english": "table"}
        ]
        while len(pairs) < 5:
            pairs.append(default_pairs[len(pairs)])
    
    return {
        "pairs": pairs[:5],  # Ensure exactly 5 pairs
        "difficulty": target_level,
        "original_level": current_level
    }

async def validate_keyword_match(session_id: str, matches: list) -> Dict[str, Any]:
    """
    Validate keyword matches.
    matches: [{"spanish": "...", "english": "..."}, ...] - user's attempted matches
    
    Returns: {
        "correct": bool,
        "score": float (0.0 to 1.0),
        "results": [{"spanish": "...", "english": "...", "is_correct": bool}, ...],
        "total": int,
        "correct_count": int
    }
    """
    # Get the original pairs from session (stored when quiz was generated)
    session = get_session(session_id)
    quiz_data = session.get("active_keyword_quiz", {})
    original_pairs = quiz_data.get("pairs", [])
    
    if not original_pairs:
        return {
            "correct": False,
            "score": 0.0,
            "results": [],
            "total": 0,
            "correct_count": 0,
            "error": "Quiz data not found"
        }
    
    # Create a mapping of correct pairs (case-insensitive)
    correct_map = {}
    for pair in original_pairs:
        key = pair["spanish"].lower().strip()
        correct_map[key] = pair["english"].lower().strip()
    
    # Validate each match
    results = []
    correct_count = 0
    
    for match in matches:
        spanish = match.get("spanish", "").lower().strip()
        english = match.get("english", "").lower().strip()
        
        correct_english = correct_map.get(spanish, "")
        is_correct = (english == correct_english) if correct_english else False
        
        if is_correct:
            correct_count += 1
        
        results.append({
            "spanish": match.get("spanish", ""),
            "english": match.get("english", ""),
            "is_correct": is_correct,
            "correct_english": correct_map.get(spanish, "") if not is_correct else None
        })
    
    total = len(results)
    score = correct_count / total if total > 0 else 0.0
    all_correct = correct_count == total
    
    return {
        "correct": all_correct,
        "score": score,
        "results": results,
        "total": total,
        "correct_count": correct_count
    }

