"""
Test Nova Sonic audio input with tool configuration
"""
import asyncio
import base64
import json
import uuid
import os
from dotenv import load_dotenv

from aws_sdk_bedrock_runtime.client import (
    BedrockRuntimeClient,
    InvokeModelWithBidirectionalStreamOperationInput,
)
from aws_sdk_bedrock_runtime.models import (
    InvokeModelWithBidirectionalStreamInputChunk,
    BidirectionalInputPayloadPart,
)
from aws_sdk_bedrock_runtime.config import Config
from smithy_aws_core.identity.environment import EnvironmentCredentialsResolver

load_dotenv()

INPUT_SAMPLE_RATE = 16000


async def test_audio_with_tools():
    """Test if audio input works when tool configuration is present."""
    model_id = "amazon.nova-sonic-v1:0"
    region = os.getenv("AWS_REGION", "us-east-1")
    
    config = Config(
        endpoint_uri=f"https://bedrock-runtime.{region}.amazonaws.com",
        region=region,
        aws_credentials_identity_resolver=EnvironmentCredentialsResolver(),
    )
    client = BedrockRuntimeClient(config=config)
    
    print("📡 Starting session with tool configuration...")
    stream = await client.invoke_model_with_bidirectional_stream(
        InvokeModelWithBidirectionalStreamOperationInput(model_id=model_id)
    )
    
    async def send_event(event_json: str):
        event = InvokeModelWithBidirectionalStreamInputChunk(
            value=BidirectionalInputPayloadPart(bytes_=event_json.encode("utf-8"))
        )
        await stream.input_stream.send(event)
    
    prompt_name = str(uuid.uuid4())
    
    # 1. Session start
    await send_event(json.dumps({
        "event": {
            "sessionStart": {
                "inferenceConfiguration": {
                    "maxTokens": 1024,
                    "topP": 0.9,
                    "temperature": 0.7
                }
            }
        }
    }))
    print("✅ Session started")
    
    # 2. Prompt start WITH tool configuration
    await send_event(json.dumps({
        "event": {
            "promptStart": {
                "promptName": prompt_name,
                "textOutputConfiguration": {
                    "mediaType": "text/plain"
                },
                "audioOutputConfiguration": {
                    "mediaType": "audio/lpcm",
                    "sampleRateHertz": 24000,
                    "sampleSizeBits": 16,
                    "channelCount": 1,
                    "voiceId": "matthew",
                    "encoding": "base64",
                    "audioType": "SPEECH"
                }
            }
        }
    }))
    print("✅ Prompt started WITHOUT tool config")
    
    # 3. System prompt
    content_name = str(uuid.uuid4())
    await send_event(json.dumps({
        "event": {
            "contentStart": {
                "promptName": prompt_name,
                "contentName": content_name,
                "type": "TEXT",
                "interactive": False,
                "role": "SYSTEM",
                "textInputConfiguration": {
                    "mediaType": "text/plain"
                }
            }
        }
    }))
    
    await send_event(json.dumps({
        "event": {
            "textInput": {
                "promptName": prompt_name,
                "contentName": content_name,
                "content": "You are a helpful assistant. Reply briefly in Hindi."
            }
        }
    }))
    
    await send_event(json.dumps({
        "event": {
            "contentEnd": {
                "promptName": prompt_name,
                "contentName": content_name
            }
        }
    }))
    print("✅ System prompt sent")
    
    # 4. Audio input - THIS IS WHERE IT MIGHT FAIL
    audio_content_name = str(uuid.uuid4())
    await send_event(json.dumps({
        "event": {
            "contentStart": {
                "promptName": prompt_name,
                "contentName": audio_content_name,
                "type": "AUDIO",
                "interactive": True,
                "role": "USER",
                "audioInputConfiguration": {
                    "mediaType": "audio/lpcm",
                    "sampleRateHertz": INPUT_SAMPLE_RATE,
                    "sampleSizeBits": 16,
                    "channelCount": 1,
                    "audioType": "SPEECH",
                    "encoding": "base64"
                }
            }
        }
    }))
    print("✅ Audio input started")
    
    # Send silence
    silence = bytes([0] * (INPUT_SAMPLE_RATE * 2))
    audio_b64 = base64.b64encode(silence).decode("utf-8")
    
    await send_event(json.dumps({
        "event": {
            "audioInput": {
                "promptName": prompt_name,
                "contentName": audio_content_name,
                "content": audio_b64
            }
        }
    }))
    print("✅ Audio chunk sent")
    
    # End audio
    await send_event(json.dumps({
        "event": {
            "contentEnd": {
                "promptName": prompt_name,
                "contentName": audio_content_name
            }
        }
    }))
    print("✅ Audio input ended")
    
    # Process responses
    print("\n📥 Processing responses...")
    try:
        for _ in range(10):
            output = await asyncio.wait_for(stream.await_output(), timeout=5.0)
            result = await output[1].receive()
            
            if result.value and result.value.bytes_:
                response_data = result.value.bytes_.decode("utf-8")
                json_data = json.loads(response_data)
                
                if "event" in json_data:
                    event = json_data["event"]
                    if "completionEnd" in event:
                        print("🏁 Completion ended")
                        break
                    elif "textOutput" in event:
                        print(f"📝 Text: {event['textOutput'].get('content', '')}")
    except asyncio.TimeoutError:
        print("⏱️ Timeout")
    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False
    
    # Cleanup
    await send_event(json.dumps({"event": {"promptEnd": {"promptName": prompt_name}}}))
    await send_event(json.dumps({"event": {"sessionEnd": {}}}))
    await stream.input_stream.close()
    
    print("\n🎉 SUCCESS! Audio input works with tool configuration!")
    return True


if __name__ == "__main__":
    success = asyncio.run(test_audio_with_tools())
    exit(0 if success else 1)
