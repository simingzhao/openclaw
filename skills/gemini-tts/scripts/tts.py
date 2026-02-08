#!/usr/bin/env python3
"""Gemini TTS - Text to Speech using Google Gemini 2.5 Pro Preview TTS"""

import argparse
import mimetypes
import os
import struct
import sys
import subprocess

def save_binary_file(file_name, data):
    with open(file_name, "wb") as f:
        f.write(data)
    print(f"File saved to: {file_name}", file=sys.stderr)

def convert_to_wav(audio_data: bytes, mime_type: str) -> bytes:
    """Generates a WAV file header for the given audio data and parameters."""
    parameters = parse_audio_mime_type(mime_type)
    bits_per_sample = parameters["bits_per_sample"]
    sample_rate = parameters["rate"]
    num_channels = 1
    data_size = len(audio_data)
    bytes_per_sample = bits_per_sample // 8
    block_align = num_channels * bytes_per_sample
    byte_rate = sample_rate * block_align
    chunk_size = 36 + data_size

    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        chunk_size,
        b"WAVE",
        b"fmt ",
        16,
        1,
        num_channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        data_size
    )
    return header + audio_data

def parse_audio_mime_type(mime_type: str) -> dict:
    """Parses bits per sample and rate from an audio MIME type string."""
    bits_per_sample = 16
    rate = 24000
    
    parts = mime_type.split(";")
    for param in parts:
        param = param.strip()
        if param.lower().startswith("rate="):
            try:
                rate_str = param.split("=", 1)[1]
                rate = int(rate_str)
            except (ValueError, IndexError):
                pass
        elif param.startswith("audio/L"):
            try:
                bits_per_sample = int(param.split("L", 1)[1])
            except (ValueError, IndexError):
                pass
    
    return {"bits_per_sample": bits_per_sample, "rate": rate}

def generate_speech(text: str, output_path: str, voice: str = "Kore", api_key: str = None):
    """Generate speech from text using Gemini TTS."""
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        print("Installing google-genai...", file=sys.stderr)
        subprocess.check_call([sys.executable, "-m", "pip", "install", "google-genai", "-q"])
        from google import genai
        from google.genai import types
    
    if not api_key:
        api_key = os.environ.get("GEMINI_API_KEY")
    
    if not api_key:
        raise ValueError("GEMINI_API_KEY not set")
    
    client = genai.Client(api_key=api_key)
    model = "gemini-2.5-flash-preview-tts"
    
    # Available voices: Aoede, Charon, Fenrir, Kore, Puck, Achernar, etc.
    contents = [
        types.Content(
            role="user",
            parts=[
                types.Part.from_text(text=f"Read aloud in a warm and friendly tone:\n\n{text}"),
            ],
        ),
    ]
    
    generate_content_config = types.GenerateContentConfig(
        temperature=1,
        response_modalities=["audio"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name=voice
                )
            )
        ),
    )
    
    audio_chunks = []
    mime_type = None
    
    for chunk in client.models.generate_content_stream(
        model=model,
        contents=contents,
        config=generate_content_config,
    ):
        if chunk.parts is None:
            continue
        if chunk.parts[0].inline_data and chunk.parts[0].inline_data.data:
            inline_data = chunk.parts[0].inline_data
            audio_chunks.append(inline_data.data)
            if mime_type is None:
                mime_type = inline_data.mime_type
    
    if not audio_chunks:
        raise ValueError("No audio data received")
    
    # Combine all chunks
    audio_data = b"".join(audio_chunks)
    
    # Determine output format
    if output_path.endswith(".wav"):
        wav_data = convert_to_wav(audio_data, mime_type or "audio/L16;rate=24000")
        save_binary_file(output_path, wav_data)
    elif output_path.endswith(".ogg"):
        # Save as WAV first, then convert to OGG Opus
        temp_wav = output_path.replace(".ogg", "_temp.wav")
        wav_data = convert_to_wav(audio_data, mime_type or "audio/L16;rate=24000")
        save_binary_file(temp_wav, wav_data)
        
        # Convert to OGG Opus for Telegram
        subprocess.run([
            "ffmpeg", "-y", "-i", temp_wav,
            "-c:a", "libopus", "-b:a", "48k", "-ac", "1",
            output_path
        ], check=True, capture_output=True)
        os.remove(temp_wav)
        print(f"Converted to OGG Opus: {output_path}", file=sys.stderr)
    else:
        # Raw audio
        save_binary_file(output_path, audio_data)
    
    print(output_path)
    return output_path

def main():
    parser = argparse.ArgumentParser(description="Gemini TTS - Text to Speech")
    parser.add_argument("text", help="Text to convert to speech")
    parser.add_argument("-o", "--output", default="/tmp/gemini_tts_output.wav", help="Output file path")
    parser.add_argument("-v", "--voice", default="Kore", help="Voice name (Aoede, Charon, Fenrir, Kore, Puck, Achernar)")
    parser.add_argument("--api-key", help="Gemini API key (or set GEMINI_API_KEY)")
    
    args = parser.parse_args()
    
    try:
        generate_speech(args.text, args.output, args.voice, args.api_key)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
