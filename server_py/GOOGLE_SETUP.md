# Using Google Gemini API Instead of OpenAI

To switch from OpenAI to Google Gemini:

## 1. Get a Google API Key

1. Go to [Google AI Studio](https://makersuite.google.com/app/apikey)
2. Create a new API key
3. Copy the key

## 2. Update Your `.env` File

Edit `server_py/.env`:

```bash
PROVIDER=google  # Change from 'openai' to 'google'
GOOGLE_API_KEY=your_google_api_key_here
GOOGLE_MODEL=gemini-1.5-flash-latest  # Fastest! Use gemini-pro if you get 404 errors
PORT=3002
```

## 3. Restart the Server

```bash
cd server_py
python run.py
```

That's it! The server will now use Google Gemini instead of OpenAI.

## Available Google Models

Choose in `.env` with `GOOGLE_MODEL=`:

- **`gemini-1.5-flash-latest`** (Fastest - Default) - Blazing fast, great quality
- **`gemini-pro`** (Stable fallback) - Use if you get 404 errors with 1.5 models
- **`gemini-1.5-pro-latest`** - More powerful than flash, still fast

**Note:** If you get a 404 error, your API key may not have access to Gemini 1.5 yet. Use `gemini-pro` as fallback.

## Available OpenAI Models

Choose in `.env` with `OPENAI_MODEL=`:

- **`gpt-3.5-turbo`** - Fast and cheap
- **`gpt-4`** - Most capable (default)
- **`gpt-4-turbo`** - Faster GPT-4

## Example `.env` for Fast Google Setup

```bash
PROVIDER=google
GOOGLE_API_KEY=your_key_here
GOOGLE_MODEL=gemini-1.5-flash-latest  # Fastest!
PORT=3002
```

## If You Get 404 Errors

Some API keys don't have access to Gemini 1.5 yet. Use this instead:

```bash
PROVIDER=google
GOOGLE_API_KEY=your_key_here
GOOGLE_MODEL=gemini-pro  # Stable fallback
PORT=3002
```

## Notes

- Default is `gemini-1.5-flash-latest` (fastest)
- If you see 404 errors, your API key doesn't have Gemini 1.5 access yet - switch to `gemini-pro`
- `gemini-1.5-flash-latest` is **much faster** than `gemini-pro` with similar quality
- The agent functions work the same with all models
- You can switch models anytime by changing `.env` and restarting

## Current Configuration

Check your terminal output when starting the server:
```
📡 Provider: google  # or 'openai'
```

