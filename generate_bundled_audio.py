"""
Generate bundled audio files for Flutter app using Sarvam TTS
Run this once to create the audio files, then copy them to Flutter assets
"""
import asyncio
import base64
import httpx
import os
from dotenv import load_dotenv

load_dotenv()

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")

async def generate_audio(text: str, filename: str):
    """Generate audio using Sarvam TTS and save to file"""
    url = "https://api.sarvam.ai/text-to-speech"
    
    headers = {
        "api-subscription-key": SARVAM_API_KEY,
        "Content-Type": "application/json"
    }
    
    payload = {
        "inputs": [text],
        "target_language_code": "hi-IN",
        "speaker": "shubh",
        "pace": 1.05,
        "speech_sample_rate": 24000,
        "enable_preprocessing": True,
        "model": "bulbul:v3"
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, headers=headers, timeout=10.0)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('audios') and len(data['audios']) > 0:
                wav_data = base64.b64decode(data['audios'][0])
                
                # Save to file
                with open(filename, 'wb') as f:
                    f.write(wav_data)
                
                print(f"✅ Generated: {filename} ({len(wav_data)} bytes)")
                return True
        else:
            print(f"❌ Error generating {filename}: {response.text}")
            return False

async def main():
    """Generate all bundled audio files"""
    print("🎤 Generating bundled audio files for NukkadMart...")
    print()
    
    audio_files = [
        {
            "text": "Namaste! Bataiye aapko kya chahiye?",
            "filename": "../NukkadMart/assets/audio/greeting.wav",
            "description": "Welcome greeting"
        },
        {
            "text": "Ek second, main check kar raha hun...",
            "filename": "../NukkadMart/assets/audio/checking_stock.wav",
            "description": "Filler audio for database lookup"
        },
        {
            "text": "Ruko, main dekh raha hun...",
            "filename": "../NukkadMart/assets/audio/one_moment.wav",
            "description": "Alternative filler audio"
        }
    ]
    
    for audio in audio_files:
        print(f"Generating: {audio['description']}")
        print(f"Text: {audio['text']}")
        success = await generate_audio(audio['text'], audio['filename'])
        if success:
            print(f"Saved to: {audio['filename']}")
        print()
    
    print("✅ All audio files generated!")
    print()
    print("Next steps:")
    print("1. Verify the audio files in NukkadMart/assets/audio/")
    print("2. Test playback in the Flutter app")
    print("3. Commit the audio files to git")

if __name__ == "__main__":
    asyncio.run(main())
