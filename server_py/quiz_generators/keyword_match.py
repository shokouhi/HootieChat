"""Keyword match quiz generator."""
from typing import Dict, Any
from langchain_core.messages import SystemMessage, HumanMessage
import json
import re
from .utils import get_llm, get_user_level, get_target_language, get_recent_quiz_content
from .cefr_utils import format_cefr_for_prompt, get_difficulty_guidelines
from tools import get_profile, get_session

llm = get_llm()

async def generate_keyword_match(session_id: str) -> Dict[str, Any]:
    """
    Generate a keyword match quiz with 5 target language-English word pairs.
    Returns: {
        "pairs": [{"spanish": "...", "english": "..."}, ...],  # Note: "spanish" key contains target language word
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
    
    # Get recent quiz content to avoid repetition - check ALL quiz types for words
    recent_content = get_recent_quiz_content(quiz_results, test_type=None, last_n=10)
    recent_words = recent_content.get("words", [])
    
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
    # Handle both string and list formats
    if isinstance(interests, list):
        interests = ", ".join(interests) if interests else ""
    # Use interests for TOPIC only, NEVER use name/age in content
    
    # Get target language
    target_language = get_target_language(profile)
    
    # Get CEFR description and difficulty guidelines for the target level
    cefr_info = format_cefr_for_prompt(target_level)
    difficulty_guide = get_difficulty_guidelines(target_level)
    
    # Build exclusion note for recent words
    exclusion_note = ""
    if recent_words:
        recent_words_str = ", ".join(recent_words[:15])  # Show up to 15 recent words
        exclusion_note = f"\n\nCRITICAL EXCLUSION LIST - DO NOT USE THESE WORDS: {recent_words_str}\n\nYou MUST choose COMPLETELY DIFFERENT {target_language} words that:\n- Have NOT been used in ANY recent quiz (image detection, keyword match, etc.)\n- Are NOT similar in meaning to any word in the list above\n- Are NEW, UNIQUE vocabulary that the student hasn't seen recently\n\nIf you see 'book' in the list, do NOT use 'book', 'books', 'novel', 'textbook', or any book-related word.\nIf you see 'cat' in the list, do NOT use 'cat', 'kitten', 'feline', or any cat-related word.\nChoose COMPLETELY DIFFERENT words."
    
    prompt = f"""Generate 5 {target_language}-English word pairs for a vocabulary matching exercise.

Student's CEFR Level:
{cefr_info}

VOCABULARY DIFFICULTY FOR {target_level}:
{difficulty_guide}

Requirements:
- Choose vocabulary that STRICTLY matches the vocabulary range specified in the guidelines above
- If interests provided ({interests}), choose vocabulary related to that TOPIC/THEME (e.g., if "tennis", include tennis-related words)
- NEVER use the student's actual name, age, or personal details
- Generate exactly 5 pairs
- Each pair should be one {target_language} word and its English translation
- For A1: Use ONLY the 300-500 most basic words
- For A2: Use common words (500-1000 range)
- For B1+: Can include more advanced vocabulary as specified in guidelines
- Mix different word types (nouns, verbs, adjectives, etc.)
- Personalize vocabulary to student interests when possible
{exclusion_note}

IMPORTANT: Choose words that are COMPLETELY DIFFERENT from what the student has seen recently. Think creatively and pick NEW, UNIQUE vocabulary.

Format your response EXACTLY like this:
WORD1_{target_language.upper()}: [word in {target_language}]
WORD1_ENGLISH: word in English

WORD2_{target_language.upper()}: [word in {target_language}]
WORD2_ENGLISH: word in English

(Continue for all 5 pairs)

Example for A1-A2 ({target_language}):
[Provide 5 {target_language}-English word pairs appropriate for A1-A2 level]

Generate 5 pairs now for {target_level} level:"""

    messages = [
        SystemMessage(content=f"You are a {target_language} language teacher creating vocabulary matching exercises. Always respond in the exact format requested."),
        HumanMessage(content=prompt)
    ]
    
    response = await llm.ainvoke(messages)
    content = response.content
    
    # Parse the response
    pairs = []
    lines = content.split('\n')
    
    # Look for language-specific labels (e.g., WORD1_SPANISH:, WORD1_FRENCH:, etc.)
    lang_label = target_language.upper()
    current_target_word = None
    for line in lines:
        line = line.strip()
        if line.startswith('WORD') and f'_{lang_label}:' in line:
            # Extract target language word
            parts = line.split(':', 1)
            if len(parts) == 2:
                current_target_word = parts[1].strip()
        elif line.startswith('WORD') and '_ENGLISH:' in line:
            # Extract English word
            parts = line.split(':', 1)
            if len(parts) == 2 and current_target_word:
                english = parts[1].strip()
                pairs.append({
                    "spanish": current_target_word,  # Keep "spanish" key for backward compatibility with frontend
                    "english": english
                })
                current_target_word = None
    
    # Fallback: try to parse if format is slightly different
    if len(pairs) < 5:
        # Try alternative parsing - look for any word: word patterns
        alt_pairs = re.findall(r'(\w+)\s*:\s*(\w+)', content)
        for word1, word2 in alt_pairs[:10]:  # Check more pairs in case format is different
            if len(pairs) < 5:
                # Assume first is target language, second is English
                pairs.append({"spanish": word1.strip(), "english": word2.strip()})
    
    # Ensure we have 5 pairs (fallback with generic words - this is a last resort)
    if len(pairs) < 5:
        print(f"[Keyword Match] Warning: Only found {len(pairs)} pairs for {target_language}, may need fallback")
        # The LLM should generate proper pairs in the requested format
    
    return {
        "pairs": pairs[:5],  # Ensure exactly 5 pairs
        "difficulty": target_level,
        "original_level": current_level
    }

async def validate_keyword_match(session_id: str, matches: list) -> Dict[str, Any]:
    """
    Validate keyword matches.
    matches: [{"spanish": "...", "english": "..."}, ...] - user's attempted matches (Note: "spanish" key contains target language word)
    
    Returns: {
        "correct": bool,
        "score": float (0.0 to 1.0),
        "results": [{"spanish": "...", "english": "...", "is_correct": bool}, ...],  # Note: "spanish" key contains target language word
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

