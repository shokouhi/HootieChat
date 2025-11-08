"""Unit completion quiz generator."""
from typing import Dict, Any
from langchain_core.messages import SystemMessage, HumanMessage
import json
import re
from .utils import get_llm, get_user_level
from .cefr_utils import format_cefr_for_prompt
from tools import get_profile, get_session

llm = get_llm()

async def generate_unit_completion(session_id: str) -> Dict[str, Any]:
    """
    Generate a unit completion quiz based on user's language level.
    Returns: {
        "sentence": "sentence with [MASK] placeholder",
        "masked_word": "the correct word",
        "hint": "optional hint",
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
        "A1": "A1-A2",  # Mix A1 with some A2
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
    
    prompt = f"""Generate a Spanish sentence completion exercise for a student at the following CEFR level:

{cefr_info}

Requirements:
- Create 2-3 short, related sentences (total 15-30 words)
- The content should match the student's language abilities as described above
- If interests provided ({interests}), use that TOPIC/THEME for content (e.g., if "tennis", write about tennis in general, NOT about the specific student)
- NEVER use the student's actual name, age, or personal details in the content
- Use generic subjects like "personas", "alguien", "gente", or "un estudiante" (not specific names)
- Choose ONE key word to mask (noun, verb, adjective, or adverb)
- The masked word should be appropriate for the student's level as described above
- Make the context clear enough that the word can be guessed based on the student's level

Format:
1. Write the sentences with [MASK] where the word should go
2. On a new line, write "CORRECT_ANSWER: [the masked word in Spanish]"
3. On another line, write "HINT: [a brief hint in Spanish, max 5 words]"

Example for A1-A2:
El gato está en el [MASK]. Me gusta mucho este lugar.
CORRECT_ANSWER: jardín
HINT: Un lugar al aire libre con plantas

Example for B1-B2:
Ayer fui al museo y vi una exposición muy [MASK]. La disfruté mucho.
CORRECT_ANSWER: interesante
HINT: Algo que capta tu atención

Generate the exercise now:"""

    messages = [
        SystemMessage(content="You are a Spanish language teacher creating sentence completion exercises. Always respond in the requested format."),
        HumanMessage(content=prompt)
    ]
    
    response = await llm.ainvoke(messages)
    content = response.content
    
    # Parse the response
    sentences = ""
    correct_answer = ""
    hint = ""
    
    # Extract sentences (everything before CORRECT_ANSWER)
    correct_match = re.search(r'CORRECT_ANSWER:\s*(.+)', content, re.IGNORECASE)
    if correct_match:
        sentences = content[:correct_match.start()].strip()
        correct_answer = correct_match.group(1).strip()
        
        # Extract hint if present
        hint_match = re.search(r'HINT:\s*(.+)', content, re.IGNORECASE)
        if hint_match:
            hint = hint_match.group(1).strip()
    
    # Clean up sentences - remove any extra formatting
    sentences = re.sub(r'\n+', ' ', sentences).strip()
    sentences = re.sub(r'\s+', ' ', sentences)
    
    # Ensure [MASK] is in the sentence
    if "[MASK]" not in sentences.upper():
        # Fallback: try to find the word and replace it
        if correct_answer:
            # Simple word boundary replacement
            sentences = re.sub(r'\b' + re.escape(correct_answer) + r'\b', '[MASK]', sentences, flags=re.IGNORECASE)
    
    return {
        "sentence": sentences,
        "masked_word": correct_answer.lower().strip() if correct_answer else "",
        "hint": hint,
        "difficulty": target_level,
        "original_level": current_level
    }

async def validate_unit_completion(session_id: str, user_answer: str, masked_word: str) -> Dict[str, Any]:
    """
    Validate user's answer against the correct masked word.
    Returns: {
        "correct": bool,
        "score": float (0.0 to 1.0),
        "feedback": str
    }
    """
    user_answer_clean = user_answer.lower().strip()
    correct_answer_clean = masked_word.lower().strip()
    
    # Exact match
    if user_answer_clean == correct_answer_clean:
        return {
            "correct": True,
            "score": 1.0,
            "feedback": "¡Correcto! Bien hecho."
        }
    
    # Check for close matches (handling accents, common variations)
    # Remove accents for comparison
    def normalize(text: str) -> str:
        replacements = {
            'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u',
            'ñ': 'n'
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        return text.lower().strip()
    
    user_normalized = normalize(user_answer_clean)
    correct_normalized = normalize(correct_answer_clean)
    
    if user_normalized == correct_normalized:
        return {
            "correct": True,
            "score": 0.95,  # Slight penalty for accent errors
            "feedback": f"¡Casi perfecto! La respuesta correcta es '{masked_word}'. (Presta atención a los acentos)"
        }
    
    # Partial credit for containing the word
    if correct_answer_clean in user_answer_clean or user_answer_clean in correct_answer_clean:
        return {
            "correct": False,
            "score": 0.3,
            "feedback": f"Cerca, pero no exacto. La respuesta correcta es '{masked_word}'."
        }
    
    # Wrong answer
    return {
        "correct": False,
        "score": 0.0,
        "feedback": f"La respuesta correcta es '{masked_word}'. ¡Sigue practicando!"
    }

