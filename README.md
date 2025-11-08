# Chat with Hootie 🦉

An AI-powered Spanish language learning app with interactive quizzes, pronunciation assessment, and personalized tutoring. Think Duolingo meets ChatGPT!

## Features

- **6 Quiz Types**: Unit completion, keyword matching, pronunciation, podcast listening, reading comprehension, and image detection
- **Adaptive Learning**: Automatically adjusts difficulty based on CEFR levels (A1-C2)
- **Interactive Chat**: Conversational learning with an AI tutor named Hootie
- **Pronunciation Assessment**: Real-time feedback using Azure Speech Services
- **Audio Generation**: Podcast-style conversations with Google Text-to-Speech
- **News Reading**: Real-world Spanish content from BBC Sport RSS feeds
- **Image Recognition**: Learn vocabulary with AI-generated images

## Tech Stack

### Frontend
- React + TypeScript
- Vite
- Server-Sent Events for streaming responses

### Backend
- Python FastAPI
- LangChain for AI agent orchestration
- OpenAI GPT-4 or Google Gemini
- Azure Speech SDK (pronunciation)
- Google Cloud Text-to-Speech (audio generation)
- DALL-E 3 (image generation)

## Prerequisites

- Node.js 18+ and npm
- Python 3.9+
- FFmpeg (for audio processing)
- API Keys:
  - OpenAI API key OR Google AI API key
  - Azure Speech Services key (optional, for pronunciation)
  - Google Cloud credentials (optional, for TTS)

## Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/shokouhi/HootieChat.git
cd HootieChat
```

### 2. Backend Setup

```bash
cd server_py

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Create .env file
cp .env.example .env  # Or create manually
```

Edit `server_py/.env` with your API keys:

```env
# Required: Choose ONE provider
PROVIDER=google                    # or 'openai'

# OpenAI Configuration
OPENAI_API_KEY=your_openai_key
OPENAI_MODEL=gpt-4

# Google AI Configuration
GOOGLE_API_KEY=your_google_ai_key
GOOGLE_MODEL=gemini-2.0-flash-exp

# Server Port
PORT=3002

# Optional: For pronunciation assessment
AZURE_SPEECH_KEY=your_azure_speech_key
AZURE_SPEECH_REGION=eastus

# Optional: For podcast audio generation
GOOGLE_APPLICATION_CREDENTIALS=./tts-gcloud.json
```

### 3. Frontend Setup

```bash
cd ../web

# Install dependencies
npm install
```

### 4. Run the Application

**Terminal 1 - Backend:**
```bash
cd server_py
python run.py
```

**Terminal 2 - Frontend:**
```bash
cd web
npm run dev
```

Open http://localhost:5173 in your browser!

## Project Structure

```
HootieChat/
├── server_py/                 # Python backend
│   ├── agent.py              # Main AI agent logic
│   ├── server.py             # FastAPI server
│   ├── tools.py              # LangChain tools
│   ├── prompts.py            # System prompts
│   ├── config.py             # Configuration
│   ├── quiz_generators/      # Modular quiz generators
│   │   ├── unit_completion.py
│   │   ├── keyword_match.py
│   │   ├── pronunciation.py
│   │   ├── podcast.py
│   │   ├── reading.py
│   │   ├── image_detection.py
│   │   └── utils.py          # Shared utilities
│   └── requirements.txt
├── web/                       # React frontend
│   ├── src/
│   │   ├── App.tsx           # Main app component
│   │   ├── main.tsx          # Entry point
│   │   └── styles.css        # Duolingo-inspired styling
│   ├── public/
│   │   ├── cefr_levels.txt   # CEFR level descriptions
│   │   └── duo-icon.svg      # App icon
│   └── package.json
├── .gitignore
├── package.json               # Root package for concurrency
└── README.md
```

## API Keys Setup

### OpenAI
1. Go to https://platform.openai.com/api-keys
2. Create a new API key
3. Add to `.env`: `OPENAI_API_KEY=sk-...`

### Google AI
1. Go to https://makersuite.google.com/app/apikey
2. Create API key
3. Add to `.env`: `GOOGLE_API_KEY=...`

### Azure Speech (Optional)
1. Create a Speech Service in Azure Portal
2. Get your key and region
3. Add to `.env`: `AZURE_SPEECH_KEY=...` and `AZURE_SPEECH_REGION=eastus`

### Google Cloud TTS (Optional)
1. Create a project in Google Cloud Console
2. Enable Text-to-Speech API
3. Create a service account and download JSON key
4. Save as `server_py/tts-gcloud.json`
5. Add to `.env`: `GOOGLE_APPLICATION_CREDENTIALS=./tts-gcloud.json`

## Development

### Run from Project Root
```bash
npm run dev        # Both backend and frontend
npm run dev:server # Backend only
npm run dev:web    # Frontend only
```

### Environment Variables
All sensitive keys should be in `server_py/.env` (already in `.gitignore`)

## Quiz Types

1. **Unit Completion**: Fill in the blank with the correct Spanish word
2. **Keyword Match**: Drag-and-drop matching English words to Spanish translations
3. **Pronunciation**: Record yourself reading a Spanish sentence
4. **Podcast**: Listen to a Spanish conversation and answer questions
5. **Reading**: Read a news article and answer comprehension questions
6. **Image Detection**: Identify objects in AI-generated images

## CEFR Levels

The app adapts to 6 proficiency levels:
- **A1**: Beginner
- **A2**: Elementary
- **B1**: Intermediate
- **B2**: Upper Intermediate
- **C1**: Advanced
- **C2**: Proficiency

## Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

MIT License - feel free to use this project for learning and teaching!

## Credits

- Built with ❤️ for language learners
- Inspired by Duolingo's UI/UX
- Powered by OpenAI, Google AI, Azure, and open-source tools

## Support

For issues or questions, open an issue on GitHub: https://github.com/shokouhi/HootieChat/issues

---

**Happy Learning! 🎉🦉**

