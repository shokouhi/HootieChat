# pip install google-cloud-texttospeech
# Requires: ffmpeg installed and GOOGLE_APPLICATION_CREDENTIALS set

import re, os, subprocess, tempfile, shutil
from google.cloud import texttospeech
from config import CONFIG

# 1) Your script (either from Gemini or your own .txt)
script_text = """
HOST_A: Hola, Juan. ¿Te gusta el tenis? 
HOST_B: ¡Sí! Me gusta mucho el tenis. 
HOST_A: ¡Qué bien! ¿Quién es tu jugador favorito? 
HOST_B: Me gusta Rafael Nadal. Es muy fuerte y juega con mucha energía. 
HOST_A: Sí, Nadal es increíble. Pero a mí me gusta más Roger Federer. 
HOST_B: Federer juega muy elegante, ¿verdad?
"""

# 2) Map speakers to distinct Spanish voices
VOICE_MAP = {
    "HOST_A": dict(language_code="es-ES", name="es-ES-Neural2-A"),  # Female Spanish voice
    "HOST_B": dict(language_code="es-ES", name="es-ES-Neural2-B"),  # Male Spanish voice
}

# 3) Replace simple <pause/> tokens with SSML breaks (optional convenience)
def to_ssml(text):
    text = text.replace("<pause/>", '<break time="400ms"/>')
    return f"<speak>{text}</speak>"

# 4) Split by speaker turns like "HOST_X: text"
turns = []
for line in script_text.splitlines():
    m = re.match(r"^(HOST_[A-Z]+):\s*(.+)$", line.strip())
    if m:
        speaker, utterance = m.group(1), m.group(2)
        turns.append((speaker, utterance))

# 5) Synthesize per turn
client = texttospeech.TextToSpeechClient()
temp_files = []

with tempfile.TemporaryDirectory() as tmpdir:
    for i, (speaker, utterance) in enumerate(turns, 1):
        voice_cfg = VOICE_MAP.get(speaker, VOICE_MAP["HOST_A"])
        synthesis_input = texttospeech.SynthesisInput(ssml=to_ssml(utterance))

        voice = texttospeech.VoiceSelectionParams(
            language_code=voice_cfg["language_code"],
            name=voice_cfg["name"],
        )
        audio_cfg = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            speaking_rate=1.0,
            pitch=0.0,
        )

        audio = client.synthesize_speech(
            input=synthesis_input, voice=voice, audio_config=audio_cfg
        )

        # Write temp file
        tmpfile = os.path.join(tmpdir, f"turn_{i}.mp3")
        with open(tmpfile, "wb") as f:
            f.write(audio.audio_content)
        temp_files.append(tmpfile)

    # 6) Concatenate using ffmpeg
    # Create concat file list
    concat_file = os.path.join(tmpdir, "concat_list.txt")
    with open(concat_file, "w") as f:
        for tf in temp_files:
            # Use forward slashes for ffmpeg even on Windows
            f.write(f"file '{tf.replace(chr(92), '/')}'\n")

    # Use ffmpeg to concatenate
    output_file = "podcast_episode.mp3"
    
    # Find ffmpeg: check PATH first, then common installation paths
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        # Try common winget installation path (version may vary)
        winget_base = os.path.join(os.environ.get("LOCALAPPDATA", ""), 
                                   "Microsoft", "WinGet", "Packages")
        if os.path.exists(winget_base):
            for item in os.listdir(winget_base):
                if "FFmpeg" in item:
                    ffmpeg_dir = os.path.join(winget_base, item)
                    # Find ffmpeg-*-full_build\bin\ffmpeg.exe
                    for subdir in os.listdir(ffmpeg_dir):
                        if subdir.startswith("ffmpeg-") and subdir.endswith("-full_build"):
                            bin_path = os.path.join(ffmpeg_dir, subdir, "bin", "ffmpeg.exe")
                            if os.path.exists(bin_path):
                                ffmpeg_path = bin_path
                                break
                    if ffmpeg_path:
                        break
        
        if not ffmpeg_path:
            print("✗ ffmpeg not found. Please restart your PowerShell after installing ffmpeg.")
            raise FileNotFoundError("ffmpeg not found")
    
    subprocess.run([
        ffmpeg_path, "-f", "concat", "-safe", "0",
        "-i", concat_file,
        "-c", "copy",  # Copy codec (fast)
        "-y",  # Overwrite
        output_file
    ], check=True, capture_output=True, text=True)

print("✓ Wrote podcast_episode.mp3")
