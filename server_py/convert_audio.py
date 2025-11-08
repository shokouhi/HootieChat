"""Convert M4A to WAV for Azure Speech SDK using ffmpeg."""
import subprocess
import sys

input_file = "../user_spanish1.m4a"
output_file = "user_spanish1.wav"

# Convert using ffmpeg (must be installed)
try:
    subprocess.run([
        "ffmpeg", "-i", input_file,
        "-acodec", "pcm_s16le",  # PCM format
        "-ar", "16000",           # 16kHz sample rate
        "-ac", "1",               # Mono
        "-y",                     # Overwrite output file
        output_file
    ], check=True, capture_output=True)
    print(f"✓ Converted to {output_file}")
except FileNotFoundError:
    print("✗ ffmpeg not found. Install it:")
    print("  winget install ffmpeg")
    print("  OR download from: https://ffmpeg.org/download.html")
    sys.exit(1)
except subprocess.CalledProcessError as e:
    print(f"✗ Conversion failed: {e}")
    sys.exit(1)

