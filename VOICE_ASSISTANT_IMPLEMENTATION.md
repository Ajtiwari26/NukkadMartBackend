# Voice Assistant Implementation

## Architecture: Hybrid Pipeline

Since Nova Sonic's bidirectional streaming API is not yet available in boto3, we implemented a hybrid approach:

```
Flutter App (PCM Audio)
    ↓ WebSocket
Backend Bridge (FastAPI)
    ↓
1. Groq Whisper (STT) → Hindi/Hinglish transcription
2. Nova Pro (LLM) → Intelligent responses with context
3. Groq TTS (TTS) → Natural Hindi voice
    ↓ WebSocket
Flutter App (MP3 Audio Playback)
```

## Components

### Backend (Python/FastAPI)

**File**: `app/services/nova_sonic_service.py`
- Groq Whisper for Hindi STT (FREE, excellent accuracy)
- Nova Pro for intelligent context-aware responses
- Groq TTS for natural Hindi voice output
- Session management with conversation history

**File**: `app/routers/voice_assistant.py`
- WebSocket endpoint: `/ws/voice/customer/{user_id}`
- Handles bidirectional audio streaming
- Integrates with Redis context service (zero DB calls during conversation)

**File**: `app/services/voice_context_service.py`
- Pre-loads nearby stores and inventory into Redis
- 30-minute TTL with auto-cleanup
- Fast product lookups during conversation

### Flutter (NukkadMart)

**File**: `lib/services/voice_cart_service.dart`
- WebSocket connection to backend
- Audio recording in PCM 16kHz mono format
- MP3 audio playback using just_audio
- Real-time transcription display

**File**: `lib/screens/ai_voice_cart_screen.dart`
- Push-to-talk interface (hold to speak)
- Chat-like conversation display
- Live cart preview
- Animated voice button with pulse effect

## Features

### Professional Shopkeeper Persona
- Greets: "Namaste sir, aapko kya chahiye?"
- Uses "Sir/Madam" and "ji" (not family terms)
- Speaks primarily in Hindi with natural English words (Hinglish)
- Short, conversational responses (1-2 sentences)

### Context-Aware Responses
- Access to nearby stores and inventory (from Redis)
- Knows product availability, brands, prices
- Can suggest alternatives if item not available
- Maintains conversation history

### Real-Time Transcription
- User speech transcribed and displayed
- AI responses shown as text
- Bilingual support (Hindi/Hinglish)

## Configuration

### Environment Variables (.env)
```bash
# AWS Bedrock
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=AKIAWKCOXS35N6FKKZOD
AWS_SECRET_ACCESS_KEY=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

# Groq API
GROQ_API_KEY=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

# Voice Settings
VOICE_LANGUAGE=hi-IN
VOICE_ENABLE_CODE_SWITCHING=true
```

### Flutter Dependencies (pubspec.yaml)
```yaml
dependencies:
  web_socket_channel: ^2.4.0
  record: ^5.0.4
  just_audio: ^0.9.36
```

## Usage Flow

1. **App Launch**: User opens NukkadMart, location is cached
2. **Connect**: User taps voice button, WebSocket connects
3. **Context Load**: Backend loads nearby stores + inventory into Redis
4. **Conversation**:
   - User holds button and speaks: "1 dudh ka packet chahiye"
   - Audio sent to backend (PCM format)
   - Groq Whisper transcribes: "1 dudh ka packet chahiye"
   - Nova Pro responds: "Ji sir, kaunsa brand chahiye? Amul ya Mother Dairy?"
   - Groq TTS converts to audio
   - Audio played in Flutter app
5. **Cart Updates**: AI can add items to cart based on conversation

## Testing

### Backend
```bash
cd NukkadBackend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Flutter
```bash
cd NukkadMart
flutter run
```

### Test Conversation
1. Open AI Voice Cart screen
2. Tap to connect
3. Hold button and say: "1 dudh ka packet chahiye"
4. Release button
5. Listen to AI response

## Performance

- **Latency**: ~2-3 seconds (Whisper + Nova Pro + TTS)
- **Cost**: Groq Whisper (FREE), Nova Pro (~$0.0008/request), Groq TTS (FREE)
- **Accuracy**: Excellent for Hindi/Hinglish
- **Context**: Zero DB calls during conversation (Redis cache)

## Future Enhancements

When Nova Sonic bidirectional API becomes available:
1. Replace hybrid pipeline with direct Nova Sonic streaming
2. Reduce latency to <1 second
3. Enable barge-in (interruption) capability
4. Real-time tool calling for cart updates

## Troubleshooting

### No audio output
- Check Groq API key is valid
- Verify just_audio permissions in AndroidManifest.xml

### Transcription errors
- Ensure audio is PCM 16kHz mono format
- Check microphone permissions

### Context shows 0 products
- Run seed script to populate store inventory
- Verify store has products linked in MongoDB
- Check Redis connection

### WebSocket connection fails
- Verify backend is running on correct IP
- Check Flutter API config matches backend URL
- Ensure firewall allows WebSocket connections
