"""Unit completion quiz generator."""
from typing import Dict, Any
from langchain_core.messages import SystemMessage, HumanMessage
import json
import re
from .utils import get_llm, get_user_level, get_target_language, get_recent_quiz_content
from .cefr_utils import format_cefr_for_prompt, get_difficulty_guidelines
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
    
    # Get recent quiz content to avoid repetition
    recent_content = get_recent_quiz_content(quiz_results, test_type="unit_completion", last_n=5)
    recent_answers = recent_content.get("answers", [])
    
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
    # Handle both string and list formats
    if isinstance(interests, list):
        interests = ", ".join(interests) if interests else ""
    # Use interests for TOPIC only, NEVER use name/age in content
    
    # Get target language
    target_language = get_target_language(profile)
    
    # Get CEFR description and difficulty guidelines for the target level
    cefr_info = format_cefr_for_prompt(target_level)
    difficulty_guide = get_difficulty_guidelines(target_level)
    
    # Build exclusion note for recent answers
    exclusion_note = ""
    if recent_answers:
        recent_answers_str = ", ".join(recent_answers[:5])  # Show up to 5 recent answers
        exclusion_note = f"\n\nCRITICAL: DO NOT use these recently used words as the masked answer: {recent_answers_str}\nYou MUST choose a DIFFERENT word that has NOT been used recently."
    
    prompt = f"""Generate a {target_language} sentence completion exercise for a student at the following CEFR level:

{cefr_info}

DIFFICULTY GUIDELINES FOR {target_level}:
{difficulty_guide}

Requirements:
- Create 2-3 short, related sentences (total 15-30 words for A1-A2, up to 50 words for higher levels)
- STRICTLY MATCH the vocabulary, grammar, and sentence complexity to the guidelines above
- If interests provided ({interests}), use that TOPIC/THEME for content (e.g., if "tennis", write about tennis in general, NOT about the specific student)
- NEVER use the student's actual name, age, or personal details in the content
- Use generic subjects like "personas", "alguien", "gente", or "un estudiante" (not specific names)
- Choose ONE key word to mask (noun, verb, adjective, or adverb) - the masked word MUST match the vocabulary level specified above
- Make the context clear enough that the word can be guessed, but ensure the entire exercise matches the student's level
{exclusion_note}

Format:
1. Write the sentences with [MASK] where the word should go
2. On a new line, write "CORRECT_ANSWER: [the masked word in {target_language}]"
3. On another line, write "HINT: [a brief hint in {target_language}, max 5 words]"

Example for A1-A2 ({target_language}):
[Provide examples in {target_language} appropriate for A1-A2 level]

Example for B1-B2 ({target_language}):
[Provide examples in {target_language} appropriate for B1-B2 level]

Generate the exercise now:"""

    messages = [
        SystemMessage(content=f"You are a {target_language} language teacher creating sentence completion exercises. Always respond in the requested format."),
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

async def validate_unit_completion(session_id: str, user_answer: str, masked_word: str, sentence: str) -> Dict[str, Any]:
    """
    Validate user's answer by checking if it fits grammatically and contextually in the sentence.
    Returns: {
        "correct": bool,
        "score": float (0.0 to 1.0),
        "feedback": str
    }
    """
    from .utils import get_llm
    from langchain_core.messages import SystemMessage, HumanMessage
    from tools import get_profile
    import re
    
    # Get target language for feedback
    profile_str = await get_profile.ainvoke({"session_id": session_id})
    try:
        profile = json.loads(profile_str)
        target_language = profile.get("target_language", "English")
    except:
        target_language = "English"
    
    user_answer_clean = user_answer.strip()
    correct_answer_clean = masked_word.strip()
    sentence_clean = sentence.strip()
    
    # First check exact match (fast path)
    if user_answer_clean.lower() == correct_answer_clean.lower():
        return {
            "correct": True,
            "score": 1.0,
            "feedback": "Correct! Well done."
        }
    
    # Replace [MASK] or [mask] with the user's answer to create the test sentence
    test_sentence = re.sub(r'\[MASK\]', user_answer_clean, sentence_clean, flags=re.IGNORECASE)
    
    # Use LLM to check if the answer fits grammatically and contextually
    llm = get_llm()
    prompt = f"""Evaluate if the student's answer fits correctly in the sentence.

Original sentence with [MASK]:
{sentence_clean}

Sentence with the student's answer:
{test_sentence}

Student's answer: "{user_answer_clean}"
Expected correct answer: "{correct_answer_clean}"

IMPORTANT: 
- Do NOT look for the answer to be semantically equivalent to the correct answer
- Evaluate if the student's answer:
  1. Fits GRAMMATICALLY in the sentence (agreement, gender, number, etc.)
  2. Makes CONTEXTUAL SENSE in the sentence (not absurd or incoherent)

Examples:
- "I like to play tennis. It is a very [MASK] sport"
  - "interesting" ✓ (grammatically correct, makes sense)
  - "fun" ✓ (grammatically correct, makes sense, even though different from "interesting")
  - "cat" ✗ (doesn't make contextual sense - "a very cat sport" is absurd)
  - "house" ✗ (doesn't make contextual sense - "a very house sport" is absurd)

Respond ONLY with JSON in this exact format:
{{
    "grammatically_correct": true/false,
    "contextually_makes_sense": true/false,
    "score": 0.0-1.0,
    "reason": "brief explanation in English"
}}

If it is grammatically correct AND makes contextual sense, score must be >= 0.8. If not, score must be < 0.8."""

    messages = [
        SystemMessage(content=f"You are an evaluator of sentence completion exercises in {target_language}. Evaluate if the answer fits grammatically and contextually, not if it is semantically equivalent to the expected answer."),
        HumanMessage(content=prompt)
    ]
    
    try:
        response = await llm.ainvoke(messages)
        content = response.content.strip()
        
        # Parse JSON from response
        if content.startswith("```json"):
            content = content[7:]
        elif content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3].strip()
        
        result = json.loads(content)
        grammatically_correct = result.get("grammatically_correct", False)
        contextually_makes_sense = result.get("contextually_makes_sense", False)
        score = float(result.get("score", 0.0))
        reason = result.get("reason", "")
        
        # Ensure score is in valid range
        score = max(0.0, min(1.0, score))
        
        # Accept if both grammatical and contextual checks pass, or if score is high enough
        if (grammatically_correct and contextually_makes_sense) or score >= 0.8:
            return {
                "correct": True,
                "score": score,
                "feedback": "Correct! Well done." if score >= 0.95 else f"Good! {reason if reason else 'Answer accepted.'}"
            }
        else:
            return {
                "correct": False,
                "score": score,
                "feedback": f"The correct answer is '{masked_word}'. {reason if reason else 'Keep practicing!'}"
            }
    except Exception as e:
        print(f"[Quiz Val] Error in validation: {e}")
        import traceback
        traceback.print_exc()
        # Fallback to exact match check
        if correct_answer_clean.lower() in user_answer_clean.lower() or user_answer_clean.lower() in correct_answer_clean.lower():
            return {
                "correct": False,
                "score": 0.5,
                "feedback": f"Close, but not exact. The correct answer is '{masked_word}'."
            }
        return {
            "correct": False,
            "score": 0.0,
            "feedback": f"The correct answer is '{masked_word}'. Keep practicing!"
        }

