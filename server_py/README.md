# Chat with Hootie - Python Server

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Create `.env` file:
```
PROVIDER=openai  # or 'google'
OPENAI_API_KEY=your_openai_key_here
GOOGLE_API_KEY=your_google_key_here  # if using Google
PORT=3001
```

3. Run server:
```bash
python server.py
# or
uvicorn server:app --reload --port 3001
```

## Features

- **Agentic Architecture**: Uses LangChain with function calling capabilities
- **Multi-Provider**: Supports both OpenAI and Google Gemini APIs
- **Function Calling**: Tools for profile management, assessment, and lesson planning
- **Streaming**: Server-Sent Events for real-time response streaming

## Agent Tools

- `upsert_profile`: Save/update user profile
- `get_profile`: Fetch user profile for personalization
- `save_assessment`: Save CEFR assessment results

