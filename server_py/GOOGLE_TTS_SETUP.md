# Google Text-to-Speech Setup

Google Cloud Text-to-Speech requires **service account credentials**, not just an API key.

## Setup Steps

1. **Go to Google Cloud Console**
   - Visit: https://console.cloud.google.com/

2. **Create a Service Account**
   - Go to: IAM & Admin → Service Accounts
   - Click "Create Service Account"
   - Name it (e.g., "text-to-speech-service")
   - Grant role: "Cloud Text-to-Speech User"
   - Click "Done"

3. **Create a Key**
   - Click on your new service account
   - Go to "Keys" tab
   - Click "Add Key" → "Create new key"
   - Choose "JSON" format
   - Download the JSON file

4. **Set the Credentials Path**

Add to your `server_py/.env`:

```bash
GOOGLE_APPLICATION_CREDENTIALS=path/to/your-service-account-key.json
```

Or set it in PowerShell before running:

```powershell
$env:GOOGLE_APPLICATION_CREDENTIALS="C:\path\to\your-key.json"
python podcast.py
```

5. **Enable the API**
   - Go to: APIs & Services → Library
   - Search for "Cloud Text-to-Speech API"
   - Click "Enable"

## Alternative: Use the same Google API key

If you want to use the same GOOGLE_API_KEY from your `.env`, you'll need to use Google's REST API instead of the Cloud client library. The current `podcast.py` uses the Cloud client which requires service account credentials.

## Running the Script

Once credentials are set:

```bash
python podcast.py
```

This will generate `podcast_episode.mp3` with natural-sounding Spanish dialogue.

