from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from agent import build_agent
from config import CONFIG
import json
import asyncio

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

run_step = build_agent()

class ChatRequest(BaseModel):
    sessionId: str
    message: str

class QuizResultRequest(BaseModel):
    sessionId: str
    testType: str  # unit_completion | keyword_match | pronunciation | podcast | reading | image_detection
    userInput: str
    score: float  # 0.0 to 1.0 or percentage

class UnitCompletionGenerateRequest(BaseModel):
    sessionId: str

class UnitCompletionValidateRequest(BaseModel):
    sessionId: str
    userAnswer: str
    maskedWord: str  # The correct answer to compare against
    sentence: str  # The full sentence with [MASK] placeholder

class KeywordMatchGenerateRequest(BaseModel):
    sessionId: str

class KeywordMatchValidateRequest(BaseModel):
    sessionId: str
    matches: list  # [{"spanish": "...", "english": "..."}, ...]

class ImageDetectionGenerateRequest(BaseModel):
    sessionId: str

class ImageDetectionValidateRequest(BaseModel):
    sessionId: str
    userAnswer: str
    correctWord: str

class PodcastGenerateRequest(BaseModel):
    sessionId: str

class PodcastValidateRequest(BaseModel):
    sessionId: str
    userAnswer: str
    correctAnswer: str

class PronunciationGenerateRequest(BaseModel):
    sessionId: str

class PronunciationValidateRequest(BaseModel):
    sessionId: str
    referenceText: str
    # Audio will be sent as binary in multipart form

class ReadingGenerateRequest(BaseModel):
    sessionId: str

class ReadingValidateRequest(BaseModel):
    sessionId: str
    userAnswer: str
    articleText: str
    question: str

@app.get("/health")
async def health():
    return {"ok": True}

@app.post("/api/chat")
async def chat(request: ChatRequest):
    """Chat endpoint with SSE streaming."""
    try:
        print(f"[Chat] Session {request.sessionId}, message: {request.message[:50]}...")
        
        # Generate reply
        reply_data = await run_step(request.sessionId, request.message)
        print(f"[Chat] Reply received")
        
        # Parse reply (may be JSON with test_type or plain string)
        try:
            reply_obj = json.loads(reply_data)
            reply_text = reply_obj.get("reply", reply_data)
            test_type = reply_obj.get("test_type", None)
        except:
            reply_text = reply_data
            test_type = None
        
        async def generate():
            # Send test type FIRST so frontend can show quiz immediately
            if test_type:
                print(f"[Chat] 📤 Sending test_type: {test_type}")
                print(f"[Chat] 📤 Reply text length: {len(reply_text)} chars")
                yield f"data: {json.dumps({'test_type': test_type})}\n\n"
                # Small delay to ensure frontend processes test_type before message
                await asyncio.sleep(0.1)
            else:
                print(f"[Chat] ℹ️ No test_type (reply only, no quiz)")
            
            # Chunk the reply for streaming (teacher's message)
            chunks = [reply_text[i:i+200] for i in range(0, len(reply_text), 200)] or [reply_text]
            for chunk in chunks:
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"
                await asyncio.sleep(0.02)
            yield f"data: {json.dumps({'done': True})}\n\n"
        
        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            }
        )
    except Exception as e:
        error_msg = str(e)
        print(f"[Chat Error]", e)
        import traceback
        traceback.print_exc()
        
        async def error_stream():
            yield f"data: {json.dumps({'error': error_msg})}\n\n"
        return StreamingResponse(error_stream(), media_type="text/event-stream")

@app.post("/api/quiz-result")
async def submit_quiz_result(request: QuizResultRequest):
    """Submit quiz/test result and get AI teacher feedback."""
    try:
        from tools import save_quiz_result, get_session
        
        print(f"[Quiz] Session {request.sessionId}, type: {request.testType}, score: {request.score}")
        
        # Save quiz result
        result = await save_quiz_result.ainvoke({
            "session_id": request.sessionId,
            "test_type": request.testType,
            "user_input": request.userInput,
            "score": request.score
        })
        
        # Get AI teacher feedback based on result
        session = get_session(request.sessionId)
        recent_history = session.get("history", [])[-2:] if len(session.get("history", [])) >= 2 else session.get("history", [])
        
        # Generate feedback using the agent
        feedback_prompt = f"""The student just completed a {request.testType} test.
User input: {request.userInput}
Score: {request.score * 100:.1f}%

Provide brief, encouraging feedback (2-3 sentences max):
- Acknowledge their effort
- Point out what they did well or what needs improvement
- Encourage them to continue"""
        
        feedback_reply = await run_step(request.sessionId, feedback_prompt)
        
        # Parse feedback reply
        try:
            feedback_obj = json.loads(feedback_reply)
            feedback_text = feedback_obj.get("reply", feedback_reply)
        except:
            feedback_text = feedback_reply
        
        return {
            "success": True,
            "result": json.loads(result),
            "feedback": feedback_text
        }
    except Exception as e:
        print(f"[Quiz Error]", e)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/quiz/unit-completion/generate")
async def generate_unit_completion_quiz(request: UnitCompletionGenerateRequest):
    """Generate a unit completion quiz for the user."""
    try:
        from quiz_generators import generate_unit_completion
        
        print(f"[Quiz Gen] Session {request.sessionId}, generating unit completion quiz")
        
        quiz_data = await generate_unit_completion(request.sessionId)
        
        if not quiz_data.get("masked_word"):
            raise HTTPException(status_code=500, detail="Failed to generate quiz - missing masked word")
        
        return {
            "success": True,
            "quiz": {
                "sentence": quiz_data["sentence"],
                "hint": quiz_data.get("hint", ""),
                "difficulty": quiz_data.get("difficulty", "A1"),
                "original_level": quiz_data.get("original_level", "A1")
            },
            "masked_word": quiz_data["masked_word"]  # Send masked word to frontend for validation
        }
    except Exception as e:
        print(f"[Quiz Gen Error]", e)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/quiz/unit-completion/validate")
async def validate_unit_completion_answer(request: UnitCompletionValidateRequest):
    """Validate user's answer for unit completion quiz."""
    try:
        from quiz_generators import validate_unit_completion
        from tools import save_quiz_result
        
        print(f"[Quiz Val] Session {request.sessionId}, answer: {request.userAnswer[:20]}...")
        
        # Validate the answer
        validation = await validate_unit_completion(
            request.sessionId,
            request.userAnswer,
            request.maskedWord,
            request.sentence
        )
        
        # Save quiz result with context for LLM scoring
        result = await save_quiz_result.ainvoke({
            "session_id": request.sessionId,
            "test_type": "unit_completion",
            "user_input": request.userAnswer,
            "score": validation["score"],
            "context": {
                "expected_answer": request.maskedWord,
                "difficulty_level": validation.get("difficulty", "A1"),
                "raw_metrics": f"Correct: {validation['correct']}, Score: {validation['score']:.2f}"
            }
        })
        
        # Send notification to agent that quiz is complete
        # The agent will pick this up in the next turn
        completion_notification = f"El estudiante completó el ejercicio de completar oración. Respuesta del usuario: '{request.userAnswer}'. Respuesta correcta: '{request.maskedWord}'. Puntuación: {validation['score']*100:.0f}%."
        
        return {
            "success": True,
            "correct": validation["correct"],
            "score": validation["score"],
            "feedback": validation["feedback"],
            "correct_answer": request.maskedWord,
            "result_id": json.loads(result).get("timestamp", ""),
            "agent_notification": completion_notification  # Frontend can send this to chat
        }
    except Exception as e:
        print(f"[Quiz Val Error]", e)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/quiz/keyword-match/generate")
async def generate_keyword_match_quiz(request: KeywordMatchGenerateRequest):
    """Generate a keyword match quiz for the user."""
    try:
        from quiz_generators import generate_keyword_match
        from tools import get_session
        
        print(f"[Quiz Gen] Session {request.sessionId}, generating keyword match quiz")
        
        quiz_data = await generate_keyword_match(request.sessionId)
        
        if not quiz_data.get("pairs") or len(quiz_data["pairs"]) != 5:
            raise HTTPException(status_code=500, detail="Failed to generate quiz - invalid pairs")
        
        # Store quiz data in session for validation
        session = get_session(request.sessionId)
        session["active_keyword_quiz"] = quiz_data
        
        return {
            "success": True,
            "quiz": {
                "pairs": quiz_data["pairs"],
                "difficulty": quiz_data.get("difficulty", "A1"),
                "original_level": quiz_data.get("original_level", "A1")
            }
        }
    except Exception as e:
        print(f"[Quiz Gen Error]", e)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/quiz/keyword-match/validate")
async def validate_keyword_match_answer(request: KeywordMatchValidateRequest):
    """Validate user's keyword matches."""
    try:
        from quiz_generators import validate_keyword_match
        from tools import save_quiz_result, get_session
        
        print(f"[Quiz Val] Session {request.sessionId}, validating {len(request.matches)} matches")
        
        # Validate the matches
        validation = await validate_keyword_match(
            request.sessionId,
            request.matches
        )
        
        # Calculate overall score
        score = validation["score"]
        all_correct = validation["correct"]
        
        # Build user input string for saving
        user_input = ", ".join([f"{m.get('spanish', '')}={m.get('english', '')}" for m in request.matches])
        
        # Get difficulty from session
        session = get_session(request.sessionId)
        quiz_data = session.get("active_keyword_quiz", {})
        original_pairs = quiz_data.get("pairs", [])
        
        # Extract target language words from original pairs for tracking
        target_lang_words = []
        for pair in original_pairs:
            # Get the target language word (could be "spanish", "french", etc. depending on language)
            # Try common keys
            for key in pair.keys():
                if key != "english" and key != "ENGLISH" and isinstance(pair[key], str):
                    target_lang_words.append(pair[key].strip().lower())
                    break
        
        # Save quiz result with context for LLM scoring
        result = await save_quiz_result.ainvoke({
            "session_id": request.sessionId,
            "test_type": "keyword_match",
            "user_input": user_input,
            "score": score,
            "context": {
                "expected_answer": f"{validation['correct_count']}/{validation['total']} correct matches",
                "difficulty_level": quiz_data.get("difficulty", "A1"),
                "raw_metrics": f"Correct: {validation['correct_count']}/{validation['total']}, All correct: {all_correct}",
                "words": target_lang_words  # Store words for diversification tracking
            }
        })
        
        # Clear active quiz from session
        session = get_session(request.sessionId)
        if "active_keyword_quiz" in session:
            del session["active_keyword_quiz"]
        
        # Send notification to agent that quiz is complete
        completion_notification = f"El estudiante completó el ejercicio de emparejamiento de palabras clave. Puntuación: {score*100:.0f}% ({validation['correct_count']}/{validation['total']} correctas)."
        
        return {
            "success": True,
            "all_correct": all_correct,
            "score": score,
            "results": validation["results"],
            "total": validation["total"],
            "correct_count": validation["correct_count"],
            "result_id": json.loads(result).get("timestamp", ""),
            "agent_notification": completion_notification if all_correct else None  # Only notify when complete
        }
    except Exception as e:
        print(f"[Quiz Val Error]", e)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/quiz/image-detection/generate")
async def generate_image_detection_quiz(request: ImageDetectionGenerateRequest):
    """Generate an image detection quiz for the user."""
    try:
        from quiz_generators import generate_image_detection
        
        print(f"[Quiz Gen] Session {request.sessionId}, generating image detection quiz")
        
        quiz_data = await generate_image_detection(request.sessionId)
        
        if not quiz_data.get("object_word"):
            raise HTTPException(status_code=500, detail="Failed to generate quiz - missing object word")
        
        return {
            "success": True,
            "quiz": {
                "object_word": quiz_data["object_word"],
                "image_url": quiz_data.get("image_url"),
                "image_base64": quiz_data.get("image_base64"),
                "difficulty": quiz_data.get("difficulty", "A1"),
                "original_level": quiz_data.get("original_level", "A1")
            }
        }
    except Exception as e:
        print(f"[Quiz Gen Error]", e)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/quiz/image-detection/validate")
async def validate_image_detection_answer(request: ImageDetectionValidateRequest):
    """Validate user's answer for image detection quiz."""
    try:
        from quiz_generators import validate_image_detection
        from tools import save_quiz_result, get_session
        
        print(f"[Quiz Val] Session {request.sessionId}, answer: {request.userAnswer[:20]}...")
        
        # Validate the answer
        validation = await validate_image_detection(
            request.sessionId,
            request.userAnswer,
            request.correctWord
        )
        
        # Get difficulty from session if available
        session = get_session(request.sessionId)
        
        # Save quiz result with context for LLM scoring
        result = await save_quiz_result.ainvoke({
            "session_id": request.sessionId,
            "test_type": "image_detection",
            "user_input": request.userAnswer,
            "score": validation["score"],
            "context": {
                "expected_answer": request.correctWord,
                "difficulty_level": "A1",  # Image detection is typically A1-A2
                "raw_metrics": f"Correct: {validation['correct']}, Score: {validation['score']:.2f}"
            }
        })
        
        # Send notification to agent
        completion_notification = f"El estudiante completó el ejercicio de detección de imagen. Respuesta del usuario: '{request.userAnswer}'. Respuesta correcta: '{request.correctWord}'. Puntuación: {validation['score']*100:.0f}%."
        
        return {
            "success": True,
            "correct": validation["correct"],
            "score": validation["score"],
            "feedback": validation["feedback"],
            "correct_answer": request.correctWord,
            "result_id": json.loads(result).get("timestamp", ""),
            "agent_notification": completion_notification
        }
    except Exception as e:
        print(f"[Quiz Val Error]", e)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/quiz/podcast/generate")
async def generate_podcast_quiz(request: PodcastGenerateRequest):
    """Generate a podcast quiz for the user."""
    try:
        from quiz_generators import generate_podcast
        from tools import get_session
        
        print(f"[Quiz Gen] Session {request.sessionId}, generating podcast quiz")
        
        quiz_data = await generate_podcast(request.sessionId)
        
        if not quiz_data.get("conversation") or not quiz_data.get("question") or not quiz_data.get("answer"):
            raise HTTPException(status_code=500, detail="Failed to generate quiz - missing conversation/question/answer")
        
        # Store quiz data in session for validation
        session = get_session(request.sessionId)
        session["active_podcast_quiz"] = quiz_data
        
        return {
            "success": True,
            "quiz": {
                "conversation": quiz_data["conversation"],
                "question": quiz_data["question"],
                "difficulty": quiz_data.get("difficulty", "A1"),
                "original_level": quiz_data.get("original_level", "A1"),
                "topic": quiz_data.get("topic", ""),
                "audio_base64": quiz_data.get("audio_base64")  # Audio as base64 data URI
            },
            "correct_answer": quiz_data["answer"]  # Send to frontend for validation
        }
    except Exception as e:
        print(f"[Quiz Gen Error]", e)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/quiz/podcast/validate")
async def validate_podcast_answer(request: PodcastValidateRequest):
    """Validate user's answer for podcast quiz."""
    try:
        from quiz_generators import validate_podcast
        from tools import save_quiz_result, get_session
        
        print(f"[Quiz Val] Session {request.sessionId}, answer: {request.userAnswer[:20]}...")
        
        # Validate the answer
        validation = await validate_podcast(
            request.sessionId,
            request.userAnswer,
            request.correctAnswer
        )
        
        # Get difficulty from session
        session = get_session(request.sessionId)
        quiz_data = session.get("active_podcast_quiz", {})
        
        # Save quiz result with context for LLM scoring
        result = await save_quiz_result.ainvoke({
            "session_id": request.sessionId,
            "test_type": "podcast",
            "user_input": request.userAnswer,
            "score": validation["score"],
            "context": {
                "expected_answer": request.correctAnswer,
                "difficulty_level": quiz_data.get("difficulty", "A1"),
                "raw_metrics": f"Correct: {validation['correct']}, Score: {validation['score']:.2f}"
            }
        })
        
        # Clear active quiz from session
        session = get_session(request.sessionId)
        if "active_podcast_quiz" in session:
            del session["active_podcast_quiz"]
        
        # Send notification to agent
        completion_notification = f"El estudiante completó el ejercicio de comprensión auditiva (podcast). Respuesta del usuario: '{request.userAnswer}'. Respuesta correcta: '{request.correctAnswer}'. Puntuación: {validation['score']*100:.0f}%."
        
        return {
            "success": True,
            "correct": validation["correct"],
            "score": validation["score"],
            "feedback": validation["feedback"],
            "correct_answer": request.correctAnswer,
            "result_id": json.loads(result).get("timestamp", ""),
            "agent_notification": completion_notification
        }
    except Exception as e:
        print(f"[Quiz Val Error]", e)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/quiz/pronunciation/generate")
async def generate_pronunciation_quiz(request: PronunciationGenerateRequest):
    """Generate a pronunciation quiz for the user."""
    try:
        from quiz_generators import generate_pronunciation
        
        print(f"[Quiz Gen] Session {request.sessionId}, generating pronunciation quiz")
        
        quiz_data = await generate_pronunciation(request.sessionId)
        
        if not quiz_data.get("sentence"):
            raise HTTPException(status_code=500, detail="Failed to generate quiz - missing sentence")
        
        return {
            "success": True,
            "quiz": {
                "sentence": quiz_data["sentence"],
                "difficulty": quiz_data.get("difficulty", "A1"),
                "original_level": quiz_data.get("original_level", "A1")
            }
        }
    except Exception as e:
        print(f"[Quiz Gen Error]", e)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/quiz/pronunciation/validate")
async def validate_pronunciation_audio(
    sessionId: str = Form(...),
    referenceText: str = Form(...),
    audio: UploadFile = File(...)
):
    """Validate pronunciation from audio file."""
    try:
        from quiz_generators import validate_pronunciation
        from tools import save_quiz_result
        
        print(f"[Quiz Val] Session {sessionId}, validating pronunciation for: {referenceText[:30]}...")
        
        # Read audio file
        audio_data = await audio.read()
        
        # Validate pronunciation
        validation = await validate_pronunciation(
            sessionId,
            audio_data,
            referenceText
        )
        
        # Calculate overall score (0.0 to 1.0) from pronunciation_score (0-100)
        score = validation["pronunciation_score"] / 100.0
        
        # Build user input string (what they said)
        user_input = "Audio recording"
        if validation.get("json_result") and "DisplayText" in validation["json_result"]:
            user_input = validation["json_result"]["DisplayText"]
        
        # Save quiz result with context for LLM scoring
        result = await save_quiz_result.ainvoke({
            "session_id": sessionId,
            "test_type": "pronunciation",
            "user_input": user_input,
            "score": score,
            "context": {
                "expected_answer": referenceText,
                "difficulty_level": "A1",  # Can be enhanced to track from quiz generation
                "raw_metrics": f"Pronunciation: {validation['pronunciation_score']:.1f}%, Accuracy: {validation['accuracy_score']:.1f}%, Fluency: {validation['fluency_score']:.1f}%, Completeness: {validation['completeness_score']:.1f}%"
            }
        })
        
        # Send notification to agent
        completion_notification = f"El estudiante completó el ejercicio de pronunciación. Frase: '{referenceText}'. Puntuación de pronunciación: {validation['pronunciation_score']:.1f}/100 (Precisión: {validation['accuracy_score']:.1f}, Fluidez: {validation['fluency_score']:.1f}, Completitud: {validation['completeness_score']:.1f})."
        
        return {
            "success": True,
            "accuracy_score": validation["accuracy_score"],
            "fluency_score": validation["fluency_score"],
            "completeness_score": validation["completeness_score"],
            "pronunciation_score": validation["pronunciation_score"],
            "score": score,  # Normalized 0.0-1.0
            "result_id": json.loads(result).get("timestamp", ""),
            "agent_notification": completion_notification,
            "user_spoke": user_input
        }
    except Exception as e:
        print(f"[Quiz Val Error]", e)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/quiz/reading/generate")
async def generate_reading_quiz(request: ReadingGenerateRequest):
    """Generate a reading comprehension quiz for the user."""
    try:
        from quiz_generators import generate_reading
        from tools import get_session
        
        print(f"[Quiz Gen] Session {request.sessionId}, generating reading quiz")
        
        quiz_data = await generate_reading(request.sessionId)
        
        if not quiz_data.get("article_text") or not quiz_data.get("question"):
            raise HTTPException(status_code=500, detail="Failed to generate quiz - missing article or question")
        
        # Store quiz data in session for validation
        session = get_session(request.sessionId)
        session["active_reading_quiz"] = quiz_data
        
        return {
            "success": True,
            "quiz": {
                "article_title": quiz_data["article_title"],
                "article_text": quiz_data["article_text"],
                "question": quiz_data["question"],
                "difficulty": quiz_data.get("difficulty", "A1"),
                "original_level": quiz_data.get("original_level", "A1"),
                "original_url": quiz_data.get("original_url", "")
            }
        }
    except Exception as e:
        print(f"[Quiz Gen Error]", e)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/quiz/reading/validate")
async def validate_reading_answer(request: ReadingValidateRequest):
    """Validate user's reading comprehension answer."""
    try:
        from quiz_generators import validate_reading
        from tools import save_quiz_result, get_session
        
        print(f"[Quiz Val] Session {request.sessionId}, validating reading answer")
        
        # Validate the answer
        validation = await validate_reading(
            request.sessionId,
            request.userAnswer,
            request.articleText,
            request.question
        )
        
        # Get difficulty from session
        session = get_session(request.sessionId)
        quiz_data = session.get("active_reading_quiz", {})
        
        # Save quiz result with context for LLM scoring
        result = await save_quiz_result.ainvoke({
            "session_id": request.sessionId,
            "test_type": "reading",
            "user_input": request.userAnswer,
            "score": validation["normalized_score"],  # Store as 0.0-1.0
            "context": {
                "expected_answer": f"Question: {request.question}",
                "difficulty_level": quiz_data.get("difficulty", "A1"),
                "raw_metrics": f"Score: {validation['score']:.1f}/10, Normalized: {validation['normalized_score']:.2f}"
            }
        })
        
        # Clear active quiz from session
        session = get_session(request.sessionId)
        if "active_reading_quiz" in session:
            del session["active_reading_quiz"]
        
        # Send notification to agent
        completion_notification = f"El estudiante completó el ejercicio de comprensión lectora. Pregunta: '{request.question}'. Respuesta: '{request.userAnswer[:50]}...'. Puntuación: {validation['score']:.1f}/10."
        
        return {
            "success": True,
            "score": validation["score"],  # 1-10 scale
            "normalized_score": validation["normalized_score"],  # 0.0-1.0 scale
            "feedback": validation["feedback"],
            "explanation": validation["explanation"],
            "result_id": json.loads(result).get("timestamp", ""),
            "agent_notification": completion_notification
        }
    except Exception as e:
        print(f"[Quiz Val Error]", e)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=CONFIG.PORT)

