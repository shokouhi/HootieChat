"""Quiz generation logic for unit completion tests."""
from typing import Dict, Any, Tuple
from langchain_core.messages import SystemMessage, HumanMessage
# Import get_llm function
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import CONFIG
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI

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

from tools import get_profile, get_session
import json
import re
import base64
import requests
from io import BytesIO
import feedparser
import random

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
    from tools import get_profile
    profile_str = await get_profile.ainvoke({"session_id": session_id})
    try:
        profile = json.loads(profile_str)
    except:
        profile = {}
    
    # Get current CEFR level from quiz results or profile
    quiz_results = session.get("quiz_results", [])
    current_level = profile.get("spanish_level", "A1")
    
    # If we have quiz-based assessment, use that level
    if quiz_results:
        # Calculate average score to estimate level
        avg_score = sum(qr.get("score", 0) for qr in quiz_results) / len(quiz_results)
        if avg_score >= 0.9:
            current_level = "C2"
        elif avg_score >= 0.85:
            current_level = "C1"
        elif avg_score >= 0.7:
            current_level = "B2"
        elif avg_score >= 0.6:
            current_level = "B1"
        elif avg_score >= 0.5:
            current_level = "A2"
        else:
            current_level = "A1"
    
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
    
    prompt = f"""Generate a Spanish sentence completion exercise for a student at {target_level} level.

Requirements:
- Create 2-3 short, related sentences (total 15-30 words)
- If interests provided ({interests}), use that TOPIC/THEME for content (e.g., if "tennis", write about tennis in general, NOT about the specific student)
- NEVER use the student's actual name, age, or personal details in the content
- Use generic subjects like "personas", "alguien", "gente", or "un estudiante" (not specific names)
- Choose ONE key word to mask (noun, verb, adjective, or adverb)
- The masked word should be at {target_level} difficulty level
- Make the context clear enough that the word can be guessed

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
    from tools import get_profile
    profile_str = await get_profile.ainvoke({"session_id": session_id})
    try:
        profile = json.loads(profile_str)
    except:
        profile = {}
    
    # Get current CEFR level from quiz results or profile
    quiz_results = session.get("quiz_results", [])
    current_level = profile.get("spanish_level", "A1")
    
    # If we have quiz-based assessment, use that level
    if quiz_results:
        avg_score = sum(qr.get("score", 0) for qr in quiz_results) / len(quiz_results)
        if avg_score >= 0.9:
            current_level = "C2"
        elif avg_score >= 0.85:
            current_level = "C1"
        elif avg_score >= 0.7:
            current_level = "B2"
        elif avg_score >= 0.6:
            current_level = "B1"
        elif avg_score >= 0.5:
            current_level = "A2"
        else:
            current_level = "A1"
    
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
    
    prompt = f"""Generate 5 Spanish-English word pairs for a vocabulary matching exercise.

Requirements:
- Student level: {target_level} (CEFR)
- If interests provided ({interests}), choose vocabulary related to that TOPIC/THEME (e.g., if "tennis", include tennis-related words)
- NEVER use the student's actual name, age, or personal details
- Generate exactly 5 pairs
- Each pair should be one Spanish word and its English translation
- Words should be appropriate for {target_level} level
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
        import re
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

async def generate_image_detection(session_id: str) -> Dict[str, Any]:
    """
    Generate an image detection quiz.
    Returns: {
        "object_word": "spanish word",
        "image_url": "data:image/png;base64,..." or URL,
        "difficulty": "A1|A2|B1|B2|C1|C2"
    }
    """
    session = get_session(session_id)
    
    # Get user profile
    profile_str = await get_profile.ainvoke({"session_id": session_id})
    try:
        profile = json.loads(profile_str)
    except:
        profile = {}
    
    # Get current CEFR level
    quiz_results = session.get("quiz_results", [])
    current_level = profile.get("spanish_level", "A1")
    
    if quiz_results:
        avg_score = sum(qr.get("score", 0) for qr in quiz_results) / len(quiz_results)
        if avg_score >= 0.9:
            current_level = "C2"
        elif avg_score >= 0.85:
            current_level = "C1"
        elif avg_score >= 0.7:
            current_level = "B2"
        elif avg_score >= 0.6:
            current_level = "B1"
        elif avg_score >= 0.5:
            current_level = "A2"
        else:
            current_level = "A1"
    
    level_map = {
        "A1": "A1-A2",
        "A2": "A2-B1",
        "B1": "B1-B2",
        "B2": "B2-C1",
        "C1": "C1-C2",
        "C2": "C2"
    }
    target_level = level_map.get(current_level, "A1-A2")
    
    # Step 1: LLM picks a Spanish word for an object
    prompt1 = f"""Select a Spanish word for a common, recognizable object appropriate for {target_level} level.
    
The word should be:
- A noun (object/item)
- Common and easily recognizable
- Appropriate difficulty for {target_level}
- Something that can be clearly illustrated in a simple cartoon style

Return ONLY the Spanish word, nothing else.
Example for A1-A2: gato, mesa, libro, coche
Example for B1-B2: ordenador, bicicleta, restaurante
Example for C1-C2: microscopio, biblioteca, laboratorio

Return the word now:"""

    messages1 = [
        SystemMessage(content="You are a Spanish teacher selecting vocabulary words. Respond with ONLY the Spanish word."),
        HumanMessage(content=prompt1)
    ]
    
    response1 = await llm.ainvoke(messages1)
    object_word = response1.content.strip().lower()
    
    # Clean up the word (remove any extra text)
    object_word = re.sub(r'[^a-záéíóúñü]', '', object_word)
    
    # Step 2: Generate image using DALL-E
    # Make the prompt very specific to ensure correct object is generated
    image_prompt = f"A simple, friendly cartoon illustration of a {object_word} (a single, clear object, not a scene or multiple objects). Style: Duolingo character art, bright and colorful, minimalist design with rounded shapes, white background, centered composition. The {object_word} should be the main and only focus of the image."
    
    image_url = None
    image_base64 = None
    
    try:
        from openai import OpenAI
        client = OpenAI(api_key=CONFIG.OPENAI_API_KEY)
        image_response = client.images.generate(
            model="dall-e-3",
            prompt=image_prompt,
            size="1024x1024",
            quality="standard",
            n=1,
        )
        image_url = image_response.data[0].url
        
        # Download and convert to base64 for embedding
        img_data = requests.get(image_url).content
        image_base64 = base64.b64encode(img_data).decode('utf-8')
    except Exception as e:
        print(f"[Image Gen Error] {e}")
        # Fallback: return word without image, frontend can handle it
        pass
    
    return {
        "object_word": object_word,
        "image_url": image_url,
        "image_base64": image_base64,
        "difficulty": target_level,
        "original_level": current_level
    }

async def validate_image_detection(session_id: str, user_answer: str, correct_word: str) -> Dict[str, Any]:
    """Validate user's answer for image detection quiz."""
    user_answer_clean = user_answer.lower().strip()
    correct_word_clean = correct_word.lower().strip()
    
    # Exact match
    if user_answer_clean == correct_word_clean:
        return {
            "correct": True,
            "score": 1.0,
            "feedback": "¡Correcto! Bien hecho."
        }
    
    # Normalize (remove accents)
    def normalize(text: str) -> str:
        replacements = {
            'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u',
            'ñ': 'n'
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        return text.lower().strip()
    
    user_normalized = normalize(user_answer_clean)
    correct_normalized = normalize(correct_word_clean)
    
    if user_normalized == correct_normalized:
        return {
            "correct": True,
            "score": 0.95,
            "feedback": f"¡Casi perfecto! La respuesta correcta es '{correct_word}'. (Presta atención a los acentos)"
        }
    
    return {
        "correct": False,
        "score": 0.0,
        "feedback": f"La respuesta correcta es '{correct_word}'. ¡Sigue practicando!"
    }

async def generate_podcast(session_id: str) -> Dict[str, Any]:
    """
    Generate a podcast conversation and question.
    Returns: {
        "conversation": "text of conversation",
        "question": "comprehension question",
        "answer": "correct answer (one word ideal)",
        "difficulty": "A1|A2|B1|B2|C1|C2",
        "topic": "topic name"
    }
    """
    session = get_session(session_id)
    
    # Get user profile
    profile_str = await get_profile.ainvoke({"session_id": session_id})
    try:
        profile = json.loads(profile_str)
    except:
        profile = {}
    
    # Get current CEFR level
    quiz_results = session.get("quiz_results", [])
    current_level = profile.get("spanish_level", "A1")
    
    if quiz_results:
        avg_score = sum(qr.get("score", 0) for qr in quiz_results) / len(quiz_results)
        if avg_score >= 0.9:
            current_level = "C2"
        elif avg_score >= 0.85:
            current_level = "C1"
        elif avg_score >= 0.7:
            current_level = "B2"
        elif avg_score >= 0.6:
            current_level = "B1"
        elif avg_score >= 0.5:
            current_level = "A2"
        else:
            current_level = "A1"
    
    level_map = {
        "A1": "A1-A2",
        "A2": "A2-B1",
        "B1": "B1-B2",
        "B2": "B2-C1",
        "C1": "C1-C2",
        "C2": "C2"
    }
    target_level = level_map.get(current_level, "A1-A2")
    
    # Get interests or use random topic
    interests = profile.get("interests", "")
    if not interests or interests.strip() == "":
        topics = ["deportes", "comida", "viajes", "música", "películas", "libros", "animales", "tecnología"]
        import random
        interests = random.choice(topics)
    
    prompt = f"""Generate a short Spanish conversation between two people (Persona A and Persona B) for a listening comprehension exercise.

Requirements:
- Student level: {target_level} (CEFR)
- Topic/theme: {interests} (use this topic generally, e.g., if "tennis", write about tennis in general)
- NEVER use the student's actual name, age, or personal details in the conversation
- Use generic names like "María", "Juan", "Ana", etc. (not the student's real name)
- Maximum 7 sentences total (distributed between both speakers)
- Natural, conversational Spanish
- Appropriate vocabulary for {target_level} level
- Clear dialogue with speaker labels (Persona A:, Persona B:)

After the conversation, generate ONE comprehension question based on the conversation content. The answer should ideally be just ONE WORD in Spanish.

Format your response EXACTLY like this:

CONVERSATION:
Persona A: [first sentence]
Persona B: [response]
Persona A: [next sentence]
Persona B: [response]
[Continue until max 7 sentences total]

QUESTION: [One question in Spanish about the conversation]
ANSWER: [The correct answer, ideally one word]

Generate now:"""

    messages = [
        SystemMessage(content="You are a Spanish teacher creating listening comprehension exercises. Follow the format exactly."),
        HumanMessage(content=prompt)
    ]
    
    response = await llm.ainvoke(messages)
    content = response.content
    
    # Parse conversation and question/answer
    conversation = ""
    question = ""
    answer = ""
    
    # Extract conversation
    conv_match = re.search(r'CONVERSATION:\s*(.*?)(?=QUESTION:|$)', content, re.DOTALL | re.IGNORECASE)
    if conv_match:
        conversation = conv_match.group(1).strip()
    
    # Extract question
    q_match = re.search(r'QUESTION:\s*(.+?)(?=ANSWER:|$)', content, re.DOTALL | re.IGNORECASE)
    if q_match:
        question = q_match.group(1).strip()
    
    # Extract answer
    a_match = re.search(r'ANSWER:\s*(.+)', content, re.IGNORECASE)
    if a_match:
        answer = a_match.group(1).strip()
        # Clean answer - get first word if multiple words
        answer_words = answer.split()
        if len(answer_words) > 1:
            # Try to find the key word
            answer = answer_words[0]
        else:
            answer = answer_words[0] if answer_words else ""
    
    return {
        "conversation": conversation,
        "question": question,
        "answer": answer.lower().strip(),
        "difficulty": target_level,
        "original_level": current_level,
        "topic": interests
    }

async def validate_podcast(session_id: str, user_answer: str, correct_answer: str) -> Dict[str, Any]:
    """Validate user's answer for podcast quiz."""
    user_answer_clean = user_answer.lower().strip()
    correct_answer_clean = correct_answer.lower().strip()
    
    # Exact match
    if user_answer_clean == correct_answer_clean:
        return {
            "correct": True,
            "score": 1.0,
            "feedback": "¡Correcto! Bien hecho."
        }
    
    # Normalize (remove accents)
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
            "score": 0.95,
            "feedback": f"¡Casi perfecto! La respuesta correcta es '{correct_answer}'. (Presta atención a los acentos)"
        }
    
    # Partial match (answer contains the word or vice versa)
    if correct_answer_clean in user_answer_clean or user_answer_clean in correct_answer_clean:
        return {
            "correct": False,
            "score": 0.5,
            "feedback": f"Cerca, pero no exacto. La respuesta correcta es '{correct_answer}'."
        }
    
    return {
        "correct": False,
        "score": 0.0,
        "feedback": f"La respuesta correcta es '{correct_answer}'. ¡Sigue practicando!"
    }

async def generate_pronunciation(session_id: str) -> Dict[str, Any]:
    """
    Generate a pronunciation test sentence.
    Returns: {
        "sentence": "Spanish sentence to pronounce",
        "difficulty": "A1|A2|B1|B2|C1|C2"
    }
    """
    session = get_session(session_id)
    
    # Get user profile
    profile_str = await get_profile.ainvoke({"session_id": session_id})
    try:
        profile = json.loads(profile_str)
    except:
        profile = {}
    
    # Get current CEFR level
    quiz_results = session.get("quiz_results", [])
    current_level = profile.get("spanish_level", "A1")
    
    if quiz_results:
        avg_score = sum(qr.get("score", 0) for qr in quiz_results) / len(quiz_results)
        if avg_score >= 0.9:
            current_level = "C2"
        elif avg_score >= 0.85:
            current_level = "C1"
        elif avg_score >= 0.7:
            current_level = "B2"
        elif avg_score >= 0.6:
            current_level = "B1"
        elif avg_score >= 0.5:
            current_level = "A2"
        else:
            current_level = "A1"
    
    level_map = {
        "A1": "A1-A2",
        "A2": "A2-B1",
        "B1": "B1-B2",
        "B2": "B2-C1",
        "C1": "C1-C2",
        "C2": "C2"
    }
    target_level = level_map.get(current_level, "A1-A2")
    
    # Get interests for personalization
    interests = profile.get("interests", "")
    
    prompt = f"""Generate a short Spanish sentence (3-8 words) for pronunciation practice.

Requirements:
- Student level: {target_level} (CEFR)
- If interests provided ({interests}), use that TOPIC/THEME for the sentence content (e.g., if "tennis", write a sentence about tennis in general)
- NEVER use the student's actual name, age, or personal details
- Sentence should be natural and conversational
- Appropriate vocabulary for {target_level} level
- Good for pronunciation practice (mix of vowels, consonants, common sounds)
- Maximum 8 words, minimum 3 words

Return ONLY the sentence, nothing else. No punctuation marks except period at the end if needed.
Examples:
- A1-A2: "Me gusta el café" or "El gato es pequeño"
- B1-B2: "Me encanta viajar por España" or "Estudio medicina en la universidad"
- C1-C2: "La investigación científica requiere paciencia" or "Aprecio la diversidad cultural"

Generate the sentence now:"""

    messages = [
        SystemMessage(content="You are a Spanish teacher creating pronunciation exercises. Respond with ONLY the Spanish sentence."),
        HumanMessage(content=prompt)
    ]
    
    response = await llm.ainvoke(messages)
    sentence = response.content.strip()
    
    # Clean up the sentence (remove extra formatting, ensure proper ending)
    sentence = re.sub(r'\n+', ' ', sentence).strip()
    sentence = re.sub(r'\s+', ' ', sentence)
    # Remove period if it exists (we'll add it back if needed)
    sentence = sentence.rstrip('.')
    
    return {
        "sentence": sentence,
        "difficulty": target_level,
        "original_level": current_level
    }

async def validate_pronunciation(session_id: str, audio_data: bytes, reference_text: str) -> Dict[str, Any]:
    """
    Validate pronunciation using Azure Speech SDK.
    audio_data: Raw audio bytes (WebM or WAV format)
    reference_text: The sentence to pronounce
    
    Returns: {
        "accuracy_score": float,
        "fluency_score": float,
        "completeness_score": float,
        "pronunciation_score": float (average),
        "json_result": dict (detailed breakdown)
    }
    """
    import tempfile
    import os
    import subprocess
    
    # Azure Speech SDK configuration
    azure_key = os.getenv("AZURE_SPEECH_KEY")
    azure_region = os.getenv("AZURE_SPEECH_REGION", "eastus")
    
    if not azure_key:
        return {
            "accuracy_score": 0,
            "fluency_score": 0,
            "completeness_score": 0,
            "pronunciation_score": 0,
            "error": "AZURE_SPEECH_KEY not configured"
        }
    
    # Save audio to temporary file (WebM format)
    input_ext = '.webm'
    with tempfile.NamedTemporaryFile(delete=False, suffix=input_ext) as tmp_input:
        tmp_input.write(audio_data)
        tmp_input_path = tmp_input.name
    
    # Convert to WAV using ffmpeg if needed (Azure Speech SDK prefers WAV)
    tmp_file_path = tmp_input_path
    try:
        if input_ext == '.webm':
            # Convert WebM to WAV using ffmpeg
            tmp_wav_path = tmp_input_path.replace('.webm', '.wav')
            import shutil
            ffmpeg_path = shutil.which("ffmpeg")
            if not ffmpeg_path:
                # Try common winget installation path
                winget_base = os.path.join(os.environ.get("LOCALAPPDATA", ""), 
                                           "Microsoft", "WinGet", "Packages")
                if os.path.exists(winget_base):
                    for item in os.listdir(winget_base):
                        if "FFmpeg" in item:
                            ffmpeg_dir = os.path.join(winget_base, item)
                            for subdir in os.listdir(ffmpeg_dir):
                                if subdir.startswith("ffmpeg-") and subdir.endswith("-full_build"):
                                    bin_path = os.path.join(ffmpeg_dir, subdir, "bin", "ffmpeg.exe")
                                    if os.path.exists(bin_path):
                                        ffmpeg_path = bin_path
                                        break
                            if ffmpeg_path:
                                break
            
            if ffmpeg_path:
                subprocess.run([
                    ffmpeg_path, "-i", tmp_input_path,
                    "-acodec", "pcm_s16le",
                    "-ar", "16000",
                    "-ac", "1",
                    "-y",
                    tmp_wav_path
                ], check=True, capture_output=True)
                tmp_file_path = tmp_wav_path
                # Delete original WebM file
                os.unlink(tmp_input_path)
    except Exception as conv_e:
        print(f"[Audio Conversion Warning] {conv_e}, using original format")
        # Continue with original file if conversion fails
    
    try:
        import azure.cognitiveservices.speech as speechsdk
        
        speech_config = speechsdk.SpeechConfig(subscription=azure_key, region=azure_region)
        audio_config = speechsdk.audio.AudioConfig(filename=tmp_file_path)
        
        pron_cfg = speechsdk.PronunciationAssessmentConfig(
            reference_text=reference_text,
            grading_system=speechsdk.PronunciationAssessmentGradingSystem.HundredMark,
            granularity=speechsdk.PronunciationAssessmentGranularity.Phoneme,
            enable_miscue=True
        )
        
        rec = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config, language="es-ES")
        pron_cfg.apply_to(rec)
        result = rec.recognize_once()
        
        assessment = speechsdk.PronunciationAssessmentResult(result)
        
        # Calculate overall pronunciation score (average of accuracy, fluency, completeness)
        pronunciation_score = (
            assessment.accuracy_score +
            assessment.fluency_score +
            assessment.completeness_score
        ) / 3.0
        
        # Parse JSON result for detailed breakdown
        json_result = {}
        if hasattr(assessment, 'json_result') and assessment.json_result:
            import json
            try:
                json_result = json.loads(assessment.json_result)
            except:
                pass
        
        return {
            "accuracy_score": float(assessment.accuracy_score),
            "fluency_score": float(assessment.fluency_score),
            "completeness_score": float(assessment.completeness_score),
            "pronunciation_score": pronunciation_score,
            "json_result": json_result
        }
    except Exception as e:
        print(f"[Pronunciation Error] {e}")
        import traceback
        traceback.print_exc()
        # Return default scores on error
        return {
            "accuracy_score": 0.0,
            "fluency_score": 0.0,
            "completeness_score": 0.0,
            "pronunciation_score": 0.0,
            "json_result": {},
            "error": str(e)
        }
    finally:
        # Clean up temporary file
        try:
            os.unlink(tmp_file_path)
        except:
            pass

async def generate_reading(session_id: str) -> Dict[str, Any]:
    """
    Generate a reading comprehension test from BBC Sport RSS feed.
    Returns: {
        "article_title": "translated title",
        "article_text": "translated Spanish text",
        "question": "comprehension question in Spanish",
        "difficulty": "A1|A2|B1|B2|C1|C2",
        "original_url": "original article URL"
    }
    """
    session = get_session(session_id)
    
    # Get user profile
    profile_str = await get_profile.ainvoke({"session_id": session_id})
    try:
        profile = json.loads(profile_str)
    except:
        profile = {}
    
    # Get current CEFR level
    quiz_results = session.get("quiz_results", [])
    current_level = profile.get("spanish_level", "A1")
    
    if quiz_results:
        avg_score = sum(qr.get("score", 0) for qr in quiz_results) / len(quiz_results)
        if avg_score >= 0.9:
            current_level = "C2"
        elif avg_score >= 0.85:
            current_level = "C1"
        elif avg_score >= 0.7:
            current_level = "B2"
        elif avg_score >= 0.6:
            current_level = "B1"
        elif avg_score >= 0.5:
            current_level = "A2"
        else:
            current_level = "A1"
    
    level_map = {
        "A1": "A1-A2",
        "A2": "A2-B1",
        "B1": "B1-B2",
        "B2": "B2-C1",
        "C1": "C1-C2",
        "C2": "C2"
    }
    target_level = level_map.get(current_level, "A1-A2")
    
    # Step 1: Fetch and parse BBC Sport RSS feed
    rss_url = "https://feeds.bbci.co.uk/sport/rss.xml"
    try:
        feed = feedparser.parse(rss_url)
        entries = [e for e in feed.entries if hasattr(e, 'title') and hasattr(e, 'summary')]
        if not entries:
            raise ValueError("No entries found in RSS feed")
        
        # Pick a random article
        article = random.choice(entries)
        original_title = article.get('title', '')
        original_summary = article.get('summary', '')
        original_url = article.get('link', '')
        
        # Clean HTML tags from summary
        original_summary = re.sub(r'<[^>]+>', '', original_summary)
        original_summary = re.sub(r'\s+', ' ', original_summary).strip()
        
        # Limit article length (first 500 words max for summary)
        words = original_summary.split()
        if len(words) > 500:
            original_summary = ' '.join(words[:500])
        
    except Exception as e:
        print(f"[RSS Error] {e}")
        # Fallback article
        original_title = "Man City wins Premier League match"
        original_summary = "Manchester City defeated their opponents 2-1 in an exciting Premier League match. The team played well and scored two goals in the second half."
        original_url = "https://www.bbc.com/sport/football"
    
    # Step 2: Translate article to Spanish at user's level
    translation_prompt = f"""Translate the following English sports news article to Spanish, adapting it for a student at {target_level} CEFR level.

Original Title: {original_title}

Original Article: {original_summary}

Requirements:
- Translate to natural Spanish
- Use vocabulary appropriate for {target_level} level
- Simplify complex sentences if needed (but keep the meaning intact)
- Maintain all key information and facts
- Keep it engaging and readable
- Maximum 400 words in Spanish

Format your response EXACTLY like this:

TITLE: [Translated Spanish title]
TEXT: [Translated Spanish article text]

Translate now:"""

    messages_translate = [
        SystemMessage(content="You are a Spanish teacher translating articles for language learners. Follow the format exactly."),
        HumanMessage(content=translation_prompt)
    ]
    
    response_translate = await llm.ainvoke(messages_translate)
    translation_content = response_translate.content
    
    # Parse translation
    title_match = re.search(r'TITLE:\s*(.+?)(?=TEXT:|$)', translation_content, re.DOTALL | re.IGNORECASE)
    text_match = re.search(r'TEXT:\s*(.+)', translation_content, re.DOTALL | re.IGNORECASE)
    
    translated_title = title_match.group(1).strip() if title_match else original_title
    translated_text = text_match.group(1).strip() if text_match else original_summary
    
    # Clean up
    translated_title = re.sub(r'\n+', ' ', translated_title).strip()
    translated_text = re.sub(r'\n+', ' ', translated_text).strip()
    translated_text = re.sub(r'\s+', ' ', translated_text)
    
    # Step 3: Generate comprehension question
    question_prompt = f"""Based on the following Spanish sports article, generate ONE reading comprehension question.

Article Title: {translated_title}

Article Text: {translated_text}

Requirements:
- Question should be in Spanish
- Appropriate difficulty for {target_level} level
- Question should test understanding of key information from the article
- Question should have a clear answer that can be found in the text
- Question should be answerable with 1-3 sentences

Format your response EXACTLY like this:

QUESTION: [Your question in Spanish]

Generate the question now:"""

    messages_question = [
        SystemMessage(content="You are a Spanish teacher creating reading comprehension questions. Respond with ONLY the question in the specified format."),
        HumanMessage(content=question_prompt)
    ]
    
    response_question = await llm.ainvoke(messages_question)
    question_content = response_question.content
    
    # Extract question
    q_match = re.search(r'QUESTION:\s*(.+)', question_content, re.DOTALL | re.IGNORECASE)
    question = q_match.group(1).strip() if q_match else "¿Qué ocurrió en el artículo?"
    
    return {
        "article_title": translated_title,
        "article_text": translated_text,
        "question": question,
        "difficulty": target_level,
        "original_level": current_level,
        "original_url": original_url
    }

async def validate_reading(session_id: str, user_answer: str, article_text: str, question: str) -> Dict[str, Any]:
    """
    Validate reading comprehension answer using LLM.
    Returns: {
        "score": float (1.0 to 10.0),
        "feedback": str,
        "explanation": str
    }
    """
    prompt = f"""Evalúa la respuesta del estudiante a una pregunta de comprensión lectora.

Artículo en español:
{article_text}

Pregunta:
{question}

Respuesta del estudiante:
{user_answer}

Evalúa la respuesta del estudiante:
1. ¿La respuesta muestra comprensión del artículo?
2. ¿La respuesta responde correctamente a la pregunta?
3. ¿La respuesta está bien expresada en español?

Asigna una puntuación del 1 al 10:
- 9-10: Respuesta excelente, demuestra comprensión completa y responde perfectamente
- 7-8: Respuesta buena, muestra buena comprensión con algunos detalles menores faltantes
- 5-6: Respuesta aceptable, comprensión básica pero falta información importante
- 3-4: Respuesta parcial, muestra comprensión limitada
- 1-2: Respuesta incorrecta o muy incompleta

Formato tu respuesta EXACTLY así:

SCORE: [número del 1 al 10]
FEEDBACK: [comentario breve y alentador en español, 1-2 frases]
EXPLANATION: [explicación de por qué esta puntuación, en español, 1-2 frases]

Evalúa ahora:"""

    messages = [
        SystemMessage(content="Eres un profesor de español que evalúa respuestas de comprensión lectora. Sigue el formato exactamente."),
        HumanMessage(content=prompt)
    ]
    
    response = await llm.ainvoke(messages)
    content = response.content
    
    # Parse response
    score = 5.0  # Default score
    feedback = "Respuesta recibida."
    explanation = "Evaluación completada."
    
    score_match = re.search(r'SCORE:\s*(\d+(?:\.\d+)?)', content, re.IGNORECASE)
    if score_match:
        try:
            score = float(score_match.group(1))
            # Ensure score is between 1 and 10
            score = max(1.0, min(10.0, score))
        except:
            pass
    
    feedback_match = re.search(r'FEEDBACK:\s*(.+?)(?=EXPLANATION:|$)', content, re.DOTALL | re.IGNORECASE)
    if feedback_match:
        feedback = feedback_match.group(1).strip()
    
    explanation_match = re.search(r'EXPLANATION:\s*(.+)', content, re.DOTALL | re.IGNORECASE)
    if explanation_match:
        explanation = explanation_match.group(1).strip()
    
    # Normalize score to 0.0-1.0 for storage
    normalized_score = score / 10.0
    
    return {
        "score": score,  # 1-10 scale
        "normalized_score": normalized_score,  # 0.0-1.0 scale
        "feedback": feedback,
        "explanation": explanation
    }

