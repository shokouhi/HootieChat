"""Pronunciation quiz generator."""
from typing import Dict, Any
from langchain_core.messages import SystemMessage, HumanMessage
import json
import re
import tempfile
import os
import subprocess
import shutil
from .utils import get_llm, get_user_level
from .cefr_utils import format_cefr_for_prompt
from tools import get_profile, get_session

llm = get_llm()

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
    
    # Get interests for personalization
    interests = profile.get("interests", "")
    
    # Get CEFR description for the target level
    cefr_info = format_cefr_for_prompt(target_level)
    
    prompt = f"""Generate a short Spanish sentence (3-8 words) for pronunciation practice.

Student's CEFR Level:
{cefr_info}

Requirements:
- The sentence should match the student's language abilities as described above
- If interests provided ({interests}), use that TOPIC/THEME for the sentence content (e.g., if "tennis", write a sentence about tennis in general)
- NEVER use the student's actual name, age, or personal details
- Sentence should be natural and conversational
- Vocabulary and complexity should match the level described above
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

