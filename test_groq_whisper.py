"""
Test Groq Whisper for Hindi transcription
"""
import os
import httpx
from dotenv import load_dotenv

load_dotenv()

async def test_groq_whisper():
    """Test Groq Whisper with sample audio"""
    
    print("🎤 Testing Groq Whisper for Hindi...")
    
    groq_api_key = os.getenv('GROQ_API_KEY')
    print(f"API Key: {groq_api_key[:20]}...")
    
    # Create dummy WAV file (1 second of silence)
    # WAV header + PCM data
    sample_rate = 16000
    duration = 1
    num_samples = sample_rate * duration
    
    # WAV header (44 bytes)
    wav_header = bytearray([
        0x52, 0x49, 0x46, 0x46,  # "RIFF"
        0x00, 0x00, 0x00, 0x00,  # File size (will update)
        0x57, 0x41, 0x56, 0x45,  # "WAVE"
        0x66, 0x6D, 0x74, 0x20,  # "fmt "
        0x10, 0x00, 0x00, 0x00,  # Subchunk1Size (16 for PCM)
        0x01, 0x00,              # AudioFormat (1 = PCM)
        0x01, 0x00,              # NumChannels (1 = mono)
        0x80, 0x3E, 0x00, 0x00,  # SampleRate (16000)
        0x00, 0x7D, 0x00, 0x00,  # ByteRate (32000)
        0x02, 0x00,              # BlockAlign (2)
        0x10, 0x00,              # BitsPerSample (16)
        0x64, 0x61, 0x74, 0x61,  # "data"
        0x00, 0x00, 0x00, 0x00,  # Subchunk2Size (will update)
    ])
    
    # PCM data (silence)
    pcm_data = bytes([0] * (num_samples * 2))  # 16-bit = 2 bytes per sample
    
    # Update sizes in header
    data_size = len(pcm_data)
    file_size = 36 + data_size
    wav_header[4:8] = file_size.to_bytes(4, 'little')
    wav_header[40:44] = data_size.to_bytes(4, 'little')
    
    wav_file = bytes(wav_header) + pcm_data
    
    print(f"WAV file: {len(wav_file)} bytes")
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            files = {
                'file': ('test.wav', wav_file, 'audio/wav'),
            }
            data = {
                'model': 'whisper-large-v3-turbo',
                'language': 'hi',
                'response_format': 'json'
            }
            headers = {
                'Authorization': f'Bearer {groq_api_key}'
            }
            
            print("\n📡 Calling Groq Whisper API...")
            response = await client.post(
                'https://api.groq.com/openai/v1/audio/transcriptions',
                files=files,
                data=data,
                headers=headers
            )
            
            print(f"Status: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                print(f"✅ SUCCESS!")
                print(f"Transcription: {result.get('text', '(empty)')}")
            else:
                print(f"❌ ERROR: {response.text}")
                
    except Exception as e:
        print(f"❌ ERROR: {str(e)}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(test_groq_whisper())
