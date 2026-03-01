import asyncio
import base64
import os
import httpx
from dotenv import load_dotenv

# Replicate the core logic
async def generate_sarvam_tts(text: str) -> bytes | None:
    """Generate high-quality Hindi TTS using Sarvam AI API"""
    url = "https://api.sarvam.ai/text-to-speech"
    load_dotenv()
    api_key = os.getenv("SARVAM_API_KEY")
    if not api_key:
        print("❌ SARVAM_API_KEY environment variable is missing")
        return None

    headers = {
        "api-subscription-key": api_key,
        "Content-Type": "application/json"
    }
    payload = {
        "inputs": [text],
        "target_language_code": "hi-IN",
        "speaker": "pooja",
        "pace": 1.05,
        "speech_sample_rate": 24000,
        "enable_preprocessing": True,
        "model": "bulbul:v3"
    }
    
    print(f"Sending payload: {payload}")
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=payload, headers=headers, timeout=10.0)
            if response.status_code == 200:
                print("✅ 200 OK from Sarvam API")
                data = response.json()
                if data.get('audios') and len(data['audios']) > 0:
                    wav_data = base64.b64decode(data['audios'][0])
                    print(f"🎵 Decoded WAV data: {len(wav_data)} bytes")
                    return wav_data
                else:
                    print("❌ No 'audios' array in response")
            else:
                print(f"❌ Sarvam API error: HTTP {response.status_code} - {response.text}")
        except Exception as e:
            print(f"❌ Sarvam TTS error: {e}")
            
    return None

async def main():
    text = "Namaste! Bataiye aapko kya chahiye?"
    print(f"Testing text: '{text}'")
    
    wav_bytes = await generate_sarvam_tts(text)
    
    if wav_bytes:
        filename = "test_output.wav"
        with open(filename, "wb") as f:
            f.write(wav_bytes)
        print(f"🎉 Success! Audio saved to {filename}")
        print(f"Check the file: {os.path.abspath(filename)}")
    else:
        print("💥 Failed to get audio from Sarvam.")

if __name__ == "__main__":
    asyncio.run(main())
