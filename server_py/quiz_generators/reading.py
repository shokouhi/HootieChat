"""Reading comprehension quiz generator."""
from typing import Dict, Any
from langchain_core.messages import SystemMessage, HumanMessage
import json
import re
import feedparser
import random
from .utils import get_llm, get_user_level, get_target_language
from .cefr_utils import format_cefr_for_prompt, get_difficulty_guidelines
from tools import get_profile, get_session

llm = get_llm()

async def generate_reading(session_id: str) -> Dict[str, Any]:
    """
    Generate a reading comprehension test from BBC Sport RSS feed.
    Returns: {
        "article_title": "translated title",
        "article_text": "translated text in target language",
        "question": "comprehension question in target language",
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
    
    # Get current CEFR level - prioritize user's stated level from profile
    quiz_results = session.get("quiz_results", [])
    current_level = get_user_level(profile, quiz_results)
    
    # For reading comprehension, use the exact level (don't push higher) to ensure appropriate difficulty
    # A1 students should get A1-level content, not A1-A2
    level_map = {
        "A1": "A1",  # Keep at A1 for reading - it's already challenging
        "A2": "A2",  # Keep at A2
        "B1": "B1",
        "B2": "B2",
        "C1": "C1",
        "C2": "C2"
    }
    target_level = level_map.get(current_level, "A1")
    
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
    
    # Get target language
    target_language = get_target_language(profile)
    
    # Get CEFR description and difficulty guidelines for the target level
    cefr_info = format_cefr_for_prompt(target_level)
    difficulty_guide = get_difficulty_guidelines(target_level)
    
    # Step 2: Translate article to target language at user's level
    translation_prompt = f"""Translate the following English sports news article to {target_language}, adapting it for a student at the following CEFR level:

{cefr_info}

DIFFICULTY GUIDELINES FOR {target_level}:
{difficulty_guide}

Original Title: {original_title}

Original Article: {original_summary}

CRITICAL REQUIREMENTS - YOU MUST STRICTLY FOLLOW THE DIFFICULTY GUIDELINES ABOVE:
- VOCABULARY: Use ONLY words within the vocabulary range specified (e.g., for A1: only 300-500 most common words)
- GRAMMAR: Follow the grammar restrictions exactly as specified in the guidelines
- SENTENCE LENGTH: Respect the maximum sentence length (e.g., A1: max 8-10 words per sentence, B2: max 20-30 words)
- COMPLEXITY: Match the complexity level exactly as described in the guidelines
- For A1/A2: HEAVILY simplify - break long sentences, replace advanced vocabulary with basic equivalents
- For B1+: Can use more complex structures, but still within the guidelines
- Maximum length: 100-150 words for A1, 150-200 for A2, 200-300 for B1-B2, up to 400 for C1-C2

Requirements:
- Translate to natural {target_language} that EXACTLY matches the student's level
- Match the vocabulary, grammar, and sentence structure PRECISELY to the guidelines above
- Simplify or expand as needed to match the target level
- Maintain all key information and facts
- Keep it engaging and readable at the student's exact level

Format your response EXACTLY like this:

TITLE: [Translated {target_language} title]
TEXT: [Translated {target_language} article text]

Translate now:"""

    messages_translate = [
        SystemMessage(content=f"You are a {target_language} teacher translating articles for language learners. Follow the format exactly."),
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
    question_prompt = f"""Based on the following {target_language} sports article, generate ONE reading comprehension question for a student at the following CEFR level:

{cefr_info}

Article Title: {translated_title}

Article Text: {translated_text}

Requirements:
- Question should be in {target_language}
- The question complexity should match the student's language abilities as described above
- Question should test understanding of key information from the article
- Question should have a clear answer that can be found in the text
- Question should be answerable with 1-3 sentences, appropriate for the student's level

Format your response EXACTLY like this:

QUESTION: [Your question in {target_language}]

Generate the question now:"""

    messages_question = [
        SystemMessage(content=f"You are a {target_language} teacher creating reading comprehension questions. Respond with ONLY the question in the specified format."),
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
    Validate reading comprehension answer using LLM with semantic matching.
    Returns: {
        "score": float (1.0 to 10.0),
        "feedback": str,
        "explanation": str
    }
    """
    prompt = f"""Evaluate the student's answer to a reading comprehension question.

Article:
{article_text}

Question:
{question}

Student's answer:
{user_answer}

IMPORTANT: Evaluate the answer based on MEANING and SEMANTIC CONTENT, not on exact word matches. If the student's answer expresses the same meaning as the correct answer, even using different words, it should receive a high score.

Evaluate the student's answer:
1. Does the answer show understanding of the article?
2. Does the answer correctly respond to the question (semantically)?
3. Is the answer well expressed?

Assign a score from 1 to 10:
- 9-10: Excellent answer, demonstrates complete understanding and responds perfectly (semantically correct)
- 7-8: Good answer, shows good understanding with some minor missing details
- 5-6: Acceptable answer, basic understanding but important information is missing
- 3-4: Partial answer, shows limited understanding
- 1-2: Incorrect or very incomplete answer

Format your response EXACTLY like this:

SCORE: [number from 1 to 10]
FEEDBACK: [brief and encouraging comment, 1-2 sentences]
EXPLANATION: [explanation of why this score, 1-2 sentences]

Evaluate now:"""

    # Get target language for feedback
    from tools import get_profile
    import json
    profile_str = await get_profile.ainvoke({"session_id": session_id})
    try:
        profile = json.loads(profile_str)
        target_language = profile.get("target_language", "English")
    except:
        target_language = "English"
    
    messages = [
        SystemMessage(content=f"You are a {target_language} teacher evaluating reading comprehension answers. Evaluate based on semantic meaning, not exact word matches. Follow the format exactly."),
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

