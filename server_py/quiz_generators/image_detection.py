"""Image detection quiz generator."""
from typing import Dict, Any
from langchain_core.messages import SystemMessage, HumanMessage
import json
import re
import base64
import requests
from .utils import get_llm, get_user_level, get_target_language, get_recent_quiz_content
from .cefr_utils import format_cefr_for_prompt, get_difficulty_guidelines
from tools import get_profile, get_session
from config import CONFIG

llm = get_llm()

async def generate_image_detection(session_id: str) -> Dict[str, Any]:
    """
    Generate an image detection quiz.
    Returns: {
        "object_word": "word in target language",
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
    
    # Get recent quiz content to avoid repetition - check ALL quiz types for words
    recent_content = get_recent_quiz_content(quiz_results, test_type=None, last_n=10)
    recent_words = recent_content.get("words", [])
    
    level_map = {
        "A1": "A1-A2",
        "A2": "A2-B1",
        "B1": "B1-B2",
        "B2": "B2-C1",
        "C1": "C1-C2",
        "C2": "C2"
    }
    target_level = level_map.get(current_level, "A1-A2")
    
    # Get target language
    target_language = get_target_language(profile)
    
    # Get CEFR description and difficulty guidelines for the target level
    cefr_info = format_cefr_for_prompt(target_level)
    difficulty_guide = get_difficulty_guidelines(target_level)
    
    # Step 1: LLM picks a word in target language for an object
    # Build exclusion list for recent words
    exclusion_note = ""
    if recent_words:
        recent_words_str = ", ".join(recent_words[:15])  # Show up to 15 recent words
        exclusion_note = f"\n\nCRITICAL EXCLUSION LIST - DO NOT USE THESE WORDS: {recent_words_str}\n\nYou MUST choose a COMPLETELY DIFFERENT word that:\n- Has NOT been used in ANY recent quiz (image detection, keyword match, etc.)\n- Is NOT similar in meaning to any word in the list above\n- Is a NEW, UNIQUE object that the student hasn't seen recently\n\nIf you see 'book' in the list, do NOT use 'book', 'books', 'novel', 'textbook', or any book-related word.\nIf you see 'cat' in the list, do NOT use 'cat', 'kitten', 'feline', or any cat-related word.\nChoose something COMPLETELY DIFFERENT."
    
    prompt1 = f"""Select a {target_language} word for a common, recognizable object appropriate for a student at the following CEFR level:

{cefr_info}

VOCABULARY DIFFICULTY FOR {target_level}:
{difficulty_guide}

The word MUST:
- Be a noun (object/item)
- Be within the vocabulary range specified in the difficulty guidelines above
- Be common and easily recognizable
- Be something that can be clearly illustrated in a simple cartoon style
- For A1: Use ONLY basic everyday objects (cat, house, book, apple, etc.)
- For A2-B1: Common objects with slightly more variety
- For B2+: Can include more abstract or specialized objects
{exclusion_note}

IMPORTANT: Choose a word that is DIFFERENT from what the student has seen recently. Think creatively and pick something NEW and UNIQUE.

Return ONLY the {target_language} word, nothing else.
Example for A1-A2 ({target_language}): gato, mesa, libro, manzana
Example for B1-B2 ({target_language}): bicicleta, computadora, restaurante
Example for C1-C2 ({target_language}): arquitectura, fenómeno, dispositivo

Return the word now:"""

    messages1 = [
        SystemMessage(content=f"You are a {target_language} teacher selecting vocabulary words. Respond with ONLY the {target_language} word."),
        HumanMessage(content=prompt1)
    ]
    
    response1 = await llm.ainvoke(messages1)
    object_word = response1.content.strip().lower()
    
    # Clean up the word (remove any extra text)
    # Works for most languages with basic character filtering
    object_word = re.sub(r'[^\w\s]', '', object_word).strip()
    
    # Step 2: Translate the word to English for the image generation prompt
    # The Imagen API works best with English prompts, so we need to translate
    translation_prompt = f"""Translate this {target_language} word to English. Return ONLY the English translation, nothing else.

{target_language} word: {object_word}

English translation:"""

    messages_translate = [
        SystemMessage(content=f"You are a translator. Respond with ONLY the English word."),
        HumanMessage(content=translation_prompt)
    ]
    
    response_translate = await llm.ainvoke(messages_translate)
    english_word = response_translate.content.strip().lower()
    
    # Clean up the English translation
    english_word = re.sub(r'[^\w\s]', '', english_word).strip()
    
    print(f"[Image Gen] Translating '{object_word}' ({target_language}) to '{english_word}' (English) for image generation")
    
    # Step 3: Generate image using Google Imagen (via Gemini)
    # Use the ENGLISH word so the API generates the correct image
    # Create a realistic cartoon that closely resembles the actual object
    image_prompt = f"""A realistic cartoon illustration of a {english_word}, inspired by Duolingo's art style but maintaining accurate representation and close resemblance to the real object.

CRITICAL REQUIREMENTS:
- The {english_word} MUST be immediately recognizable and accurately represent the real object
- Maintain realistic proportions, key features, and defining characteristics of the {english_word}
- The object should closely resemble its real-world appearance (colors, shape, structure)
- Prioritize accuracy and recognizability over stylization

Style requirements (without compromising realism):
- Cartoon style inspired by Duolingo characters - friendly and approachable
- Bright, cheerful colors that match the object's natural/typical colors
- Soft, rounded edges while maintaining the object's actual shape
- Clean, simple design but with all essential features visible
- White or light neutral background
- The {english_word} as the single, centered focus
- No text, labels, speech bubbles, or additional objects
- Educational quality - suitable for language learning
- Detailed enough to be instantly identifiable

Balance: Make it look friendly and cartoon-like (Duolingo style) while ensuring it's a realistic, accurate representation that students can easily identify and learn from."""
    
    image_url = None
    image_base64 = None
    
    def generate_svg_placeholder(word: str) -> str:
        """Generate a simple SVG placeholder image for the word."""
        # Create a colorful, educational SVG placeholder
        colors = [
            "#58CC02",  # Duolingo green
            "#1CB0F6",  # Duolingo blue
            "#FFC800",  # Duolingo yellow
            "#FF9600",  # Orange
            "#CE82FF",  # Purple
        ]
        import random
        color = random.choice(colors)
        
        # Create SVG with word displayed prominently
        svg = f'''<svg width="400" height="400" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="grad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:{color};stop-opacity:1" />
      <stop offset="100%" style="stop-color:{color}88;stop-opacity:1" />
    </linearGradient>
  </defs>
  <rect width="400" height="400" fill="url(#grad)" rx="20"/>
  <circle cx="200" cy="150" r="60" fill="white" opacity="0.3"/>
  <text x="200" y="280" font-family="Arial, sans-serif" font-size="48" font-weight="bold" 
        fill="white" text-anchor="middle">{word.upper()}</text>
  <text x="200" y="320" font-family="Arial, sans-serif" font-size="24" 
        fill="white" text-anchor="middle" opacity="0.9">🖼️</text>
</svg>'''
        # Convert SVG to base64
        svg_bytes = svg.encode('utf-8')
        return base64.b64encode(svg_bytes).decode('utf-8')
    
    try:
        vertex_success = False
        
        # Try Vertex AI Imagen API first (if project ID is configured)
        if CONFIG.GOOGLE_PROJECT_ID:
            # Use Vertex AI endpoint
            location = CONFIG.GOOGLE_LOCATION
            project_id = CONFIG.GOOGLE_PROJECT_ID
            vertex_api_url = f"https://{location}-aiplatform.googleapis.com/v1/projects/{project_id}/locations/{location}/publishers/google/models/imagen-3.0-generate-001:predict"
            
            # Get access token for Vertex AI
            try:
                import google.auth
                from google.auth.transport.requests import Request
                import os
                
                credentials = None
                try:
                    # Define required scopes for Vertex AI
                    scopes = ['https://www.googleapis.com/auth/cloud-platform']
                    
                    # Try to use service account credentials if available
                    if os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
                        creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
                        # Handle relative paths
                        if not os.path.isabs(creds_path):
                            server_py_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                            creds_path = os.path.join(server_py_dir, creds_path)
                        
                        from google.oauth2 import service_account
                        credentials = service_account.Credentials.from_service_account_file(
                            creds_path,
                            scopes=scopes
                        )
                        project = project_id  # Use the project ID from config
                    else:
                        # Try default credentials with scopes
                        credentials, project = google.auth.default(scopes=scopes)
                except Exception as auth_error:
                    print(f"[Image Gen] ⚠️ Auth error: {auth_error}. Trying API key method...")
                    credentials = None
                
                headers = {
                    "Content-Type": "application/json"
                }
                
                # Add authorization header
                if credentials:
                    if not credentials.valid:
                        credentials.refresh(Request())
                    headers["Authorization"] = f"Bearer {credentials.token}"
                elif CONFIG.GOOGLE_API_KEY:
                    # Fallback: try with API key in URL (may not work for Vertex AI)
                    vertex_api_url = f"{vertex_api_url}?key={CONFIG.GOOGLE_API_KEY}"
                
                payload = {
                    "instances": [{
                        "prompt": image_prompt
                    }],
                    "parameters": {
                        "sampleCount": 1,
                        "aspectRatio": "1:1",
                        "safetyFilterLevel": "BLOCK_SOME",
                        "personGeneration": "ALLOW_ALL"
                    }
                }
                
                print(f"[Image Gen] Trying Vertex AI endpoint: {location}-aiplatform.googleapis.com")
                img_response = requests.post(
                    vertex_api_url,
                    headers=headers,
                    json=payload,
                    timeout=30
                )
                
                if img_response.status_code == 200:
                    result = img_response.json()
                    # Vertex AI response structure
                    if 'predictions' in result and len(result['predictions']) > 0:
                        prediction = result['predictions'][0]
                        if 'bytesBase64Encoded' in prediction:
                            image_base64 = prediction['bytesBase64Encoded']
                        elif 'imageBytes' in prediction:
                            image_base64 = prediction['imageBytes']
                        elif 'image' in prediction:
                            image_base64 = prediction['image']
                        else:
                            # Try to find base64 in any field
                            for key, value in prediction.items():
                                if isinstance(value, str) and len(value) > 100:
                                    image_base64 = value
                                    break
                        
                        if image_base64:
                            print(f"[Image Gen] ✅ Successfully generated image via Vertex AI Imagen API")
                            vertex_success = True
                    else:
                        print(f"[Image Gen] ⚠️ Vertex AI response missing predictions: {result}")
                elif img_response.status_code == 404:
                    print(f"[Image Gen] ⚠️ Vertex AI endpoint not found (404). Trying Generative AI Studio endpoint...")
                else:
                    error_text = img_response.text[:500] if img_response.text else "Unknown error"
                    print(f"[Image Gen] ⚠️ Vertex AI error {img_response.status_code}: {error_text}")
            except ImportError:
                print(f"[Image Gen] ⚠️ google-auth library not installed. Install with: pip install google-auth")
            except Exception as e:
                print(f"[Image Gen] ⚠️ Vertex AI error: {e}")
        
        # Fallback: Try Generative AI Studio endpoint (if Vertex AI failed or not configured)
        if not vertex_success:
            api_url_alt = "https://generativelanguage.googleapis.com/v1beta/models/imagen-3.0-generate-001:generateImages"
            
            headers = {
                "Content-Type": "application/json"
            }
            
            payload = {
                "prompt": image_prompt,
                "numberOfImages": 1,
                "aspectRatio": "1:1",
                "safetyFilterLevel": "block_some",
                "personGeneration": "allow_all"
            }
            
            print(f"[Image Gen] Trying Generative AI Studio endpoint...")
            img_response = requests.post(
                f"{api_url_alt}?key={CONFIG.GOOGLE_API_KEY}",
                headers=headers,
                json=payload,
                timeout=30
            )
            
            if img_response.status_code == 200:
                result = img_response.json()
                if 'generatedImages' in result and len(result['generatedImages']) > 0:
                    image_base64 = result['generatedImages'][0].get('bytesBase64Encoded')
                elif 'images' in result and len(result['images']) > 0:
                    image_base64 = result['images'][0].get('bytesBase64Encoded')
                elif 'imageBytes' in result:
                    image_base64 = result['imageBytes']
                if image_base64:
                    print(f"[Image Gen] ✅ Successfully generated image via Generative AI Studio")
        
        # If both failed, use SVG placeholder
        if not image_base64:
            if img_response and img_response.status_code == 404:
                print(f"[Image Gen] ⚠️ Imagen API not available (404). Using SVG placeholder.")
            elif img_response:
                error_text = img_response.text[:200] if img_response.text else "Unknown error"
                print(f"[Image Gen] ⚠️ API error {img_response.status_code}: {error_text}. Using SVG placeholder.")
            else:
                print(f"[Image Gen] ⚠️ No project ID configured. Using SVG placeholder.")
            image_base64 = generate_svg_placeholder(object_word)
            print(f"[Image Gen] ✅ Generated SVG placeholder for '{object_word}'")
        
    except ImportError:
        print("[Image Gen] requests library not available, using SVG placeholder")
        image_base64 = generate_svg_placeholder(object_word)
    except Exception as e:
        error_msg = str(e)
        print(f"[Image Gen] ⚠️ Error: {error_msg}. Using SVG placeholder.")
        # Fallback to SVG placeholder
        image_base64 = generate_svg_placeholder(object_word)
    
    return {
        "object_word": object_word,
        "image_url": image_url,
        "image_base64": image_base64,
        "difficulty": target_level,
        "original_level": current_level
    }

async def validate_image_detection(session_id: str, user_answer: str, correct_word: str) -> Dict[str, Any]:
    """Validate user's answer for image detection quiz using semantic matching."""
    from .utils import get_llm
    from langchain_core.messages import SystemMessage, HumanMessage
    from tools import get_profile
    import json
    
    # Get target language for feedback
    profile_str = await get_profile.ainvoke({"session_id": session_id})
    try:
        profile = json.loads(profile_str)
        target_language = profile.get("target_language", "English")
    except:
        target_language = "English"
    
    user_answer_clean = user_answer.strip()
    correct_word_clean = correct_word.strip()
    
    # First check exact match (fast path)
    if user_answer_clean.lower() == correct_word_clean.lower():
        return {
            "correct": True,
            "score": 1.0,
            "feedback": "Correct! Well done.",
            "user_answer": user_answer
        }
    
    # Use LLM for semantic matching
    llm = get_llm()
    prompt = f"""Evaluate if the student's word is semantically equivalent to the correct word.

Correct word: "{correct_word_clean}"
Student's word: "{user_answer_clean}"

IMPORTANT: Do not look for exact matches. Evaluate if both words refer to the same object, concept, or thing, even if they are synonyms or variations.

Examples of semantically equivalent words:
- "house" and "home" (both refer to a dwelling)
- "car" and "automobile" (both refer to a vehicle)
- "dog" and "canine" (both refer to the same animal)
- "happy" and "content" (both express the same emotional state)

Respond ONLY with JSON in this exact format:
{{
    "semantically_equivalent": true/false,
    "score": 0.0-1.0,
    "reason": "brief explanation in English"
}}

If they are semantically equivalent, score must be >= 0.8. If not, score must be < 0.8."""

    messages = [
        SystemMessage(content=f"You are a vocabulary evaluator for {target_language}. Evaluate semantic equivalence, not exact word matches."),
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
        semantically_equivalent = result.get("semantically_equivalent", False)
        score = float(result.get("score", 0.0))
        reason = result.get("reason", "")
        
        # Ensure score is in valid range
        score = max(0.0, min(1.0, score))
        
        if semantically_equivalent or score >= 0.8:
            return {
                "correct": True,
                "score": score,
                "feedback": "Correct! Well done." if score >= 0.95 else f"Good! {reason if reason else 'Answer accepted.'}",
                "user_answer": user_answer
            }
        else:
            return {
                "correct": False,
                "score": score,
                "feedback": f"The correct answer is '{correct_word}'. {reason if reason else 'Keep practicing!'}",
                "correct_answer": correct_word,
                "user_answer": user_answer
            }
    except Exception as e:
        print(f"[Quiz Val] Error in semantic validation: {e}")
        # Fallback to exact match check
        return {
            "correct": False,
            "score": 0.0,
            "feedback": f"The correct answer is '{correct_word}'. Keep practicing!",
            "correct_answer": correct_word,
            "user_answer": user_answer
        }

