"""Image detection quiz generator."""
from typing import Dict, Any
from langchain_core.messages import SystemMessage, HumanMessage
import json
import re
import base64
import requests
from .utils import get_llm, get_user_level
from .cefr_utils import format_cefr_for_prompt
from tools import get_profile, get_session
from config import CONFIG

llm = get_llm()

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
    
    # Get current CEFR level - prioritize user's stated level from profile
    quiz_results = session.get("quiz_results", [])
    current_level = get_user_level(profile, quiz_results)
    
    level_map = {
        "A1": "A1-A2",
        "A2": "A2-B1",
        "B1": "B1-B2",
        "B2": "B2-C1",
        "C1": "C1-C2",
        "C2": "C2"
    }
    target_level = level_map.get(current_level, "A1-A2")
    
    # Get CEFR description for the target level
    cefr_info = format_cefr_for_prompt(target_level)
    
    # Step 1: LLM picks a Spanish word for an object
    prompt1 = f"""Select a Spanish word for a common, recognizable object appropriate for a student at the following CEFR level:

{cefr_info}

The word should be:
- A noun (object/item)
- Common and easily recognizable
- Appropriate vocabulary for the student's level as described above
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
    image_prompt = f"A simple, friendly kindergarten cartoon illustration of a {object_word} (a single, clear object, not a scene or multiple objects). Style: simple children's book art, bright primary colors, very simple shapes with thick black outlines, minimalist design perfect for young children, white background, centered composition. The {object_word} should be the main and only focus of the image."
    
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
            "feedback": "¡Correcto! Bien hecho.",
            "user_answer": user_answer
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
            "feedback": f"¡Casi perfecto! La respuesta correcta es '{correct_word}'. (Presta atención a los acentos)",
            "user_answer": user_answer
        }
    
    return {
        "correct": False,
        "score": 0.0,
        "feedback": f"La respuesta correcta es '{correct_word}'. ¡Sigue practicando!",
        "correct_answer": correct_word,
        "user_answer": user_answer
    }

