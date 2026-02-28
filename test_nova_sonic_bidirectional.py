"""
Test Nova Sonic Bidirectional Streaming
Uses the aws_sdk_bedrock_runtime SDK (NOT boto3) for bidirectional streaming
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

# Audio config
INPUT_SAMPLE_RATE = 16000
CHANNELS = 1


class NovaSonicTest:
    def __init__(self):
        self.model_id = "amazon.nova-sonic-v1:0"
        self.region = os.getenv("AWS_REGION", "us-east-1")
        self.client = None
        self.stream = None
        self.is_active = False
        self.prompt_name = str(uuid.uuid4())
        self.content_name = str(uuid.uuid4())
        self.audio_content_name = str(uuid.uuid4())

    def _initialize_client(self):
        """Initialize the Bedrock Runtime client using the new SDK."""
        config = Config(
            endpoint_uri=f"https://bedrock-runtime.{self.region}.amazonaws.com",
            region=self.region,
            aws_credentials_identity_resolver=EnvironmentCredentialsResolver(),
        )
        self.client = BedrockRuntimeClient(config=config)

    async def send_event(self, event_json: str):
        """Send an event to the bidirectional stream."""
        event = InvokeModelWithBidirectionalStreamInputChunk(
            value=BidirectionalInputPayloadPart(bytes_=event_json.encode("utf-8"))
        )
        await self.stream.input_stream.send(event)

    async def start_session(self):
        """Start a Nova Sonic bidirectional session."""
        if not self.client:
            self._initialize_client()

        print(f"📡 Connecting to Nova Sonic ({self.model_id}) in {self.region}...")

        # Initialize the bidirectional stream
        self.stream = await self.client.invoke_model_with_bidirectional_stream(
            InvokeModelWithBidirectionalStreamOperationInput(model_id=self.model_id)
        )
        self.is_active = True
        print("✅ Bidirectional stream established!")

        # 1. Send sessionStart event
        session_start = json.dumps({
            "event": {
                "sessionStart": {
                    "inferenceConfiguration": {
                        "maxTokens": 1024,
                        "topP": 0.9,
                        "temperature": 0.7
                    }
                }
            }
        })
        await self.send_event(session_start)
        print("✅ Session started")

        # 2. Send promptStart event
        prompt_start = json.dumps({
            "event": {
                "promptStart": {
                    "promptName": self.prompt_name,
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
        })
        await self.send_event(prompt_start)
        print("✅ Prompt started")

        # 3. Send system prompt (contentStart -> textInput -> contentEnd)
        text_content_start = json.dumps({
            "event": {
                "contentStart": {
                    "promptName": self.prompt_name,
                    "contentName": self.content_name,
                    "type": "TEXT",
                    "interactive": False,
                    "role": "SYSTEM",
                    "textInputConfiguration": {
                        "mediaType": "text/plain"
                    }
                }
            }
        })
        await self.send_event(text_content_start)

        system_prompt = (
            "You are a helpful shopkeeper in India. "
            "Reply briefly in Hindi: 'Namaste sir, aapko kya chahiye?'"
        )
        text_input = json.dumps({
            "event": {
                "textInput": {
                    "promptName": self.prompt_name,
                    "contentName": self.content_name,
                    "content": system_prompt
                }
            }
        })
        await self.send_event(text_input)

        text_content_end = json.dumps({
            "event": {
                "contentEnd": {
                    "promptName": self.prompt_name,
                    "contentName": self.content_name
                }
            }
        })
        await self.send_event(text_content_end)
        print("✅ System prompt sent")

    async def send_audio_and_get_response(self):
        """Send a short audio clip and process responses."""
        
        # Start audio content
        audio_content_start = json.dumps({
            "event": {
                "contentStart": {
                    "promptName": self.prompt_name,
                    "contentName": self.audio_content_name,
                    "type": "AUDIO",
                    "interactive": True,
                    "role": "USER",
                    "audioInputConfiguration": {
                        "mediaType": "audio/lpcm",
                        "sampleRateHertz": INPUT_SAMPLE_RATE,
                        "sampleSizeBits": 16,
                        "channelCount": CHANNELS,
                        "audioType": "SPEECH",
                        "encoding": "base64"
                    }
                }
            }
        })
        await self.send_event(audio_content_start)
        print("✅ Audio input started")

        # Send 1 second of silence as test audio
        silence = bytes([0] * (INPUT_SAMPLE_RATE * 2))  # 16-bit = 2 bytes per sample
        audio_b64 = base64.b64encode(silence).decode("utf-8")
        
        audio_event = json.dumps({
            "event": {
                "audioInput": {
                    "promptName": self.prompt_name,
                    "contentName": self.audio_content_name,
                    "content": audio_b64
                }
            }
        })
        await self.send_event(audio_event)
        print("✅ Audio chunk sent (1s silence)")

        # End audio content
        audio_content_end = json.dumps({
            "event": {
                "contentEnd": {
                    "promptName": self.prompt_name,
                    "contentName": self.audio_content_name
                }
            }
        })
        await self.send_event(audio_content_end)
        print("✅ Audio input ended")

    async def end_session(self):
        """End the session gracefully."""
        prompt_end = json.dumps({
            "event": {
                "promptEnd": {
                    "promptName": self.prompt_name
                }
            }
        })
        await self.send_event(prompt_end)

        session_end = json.dumps({
            "event": {
                "sessionEnd": {}
            }
        })
        await self.send_event(session_end)
        await self.stream.input_stream.close()
        print("✅ Session ended")

    async def process_responses(self, timeout: float = 15.0):
        """Process response events from Nova Sonic."""
        event_count = 0
        print("\n📥 Processing responses...")

        try:
            while True:
                try:
                    output = await asyncio.wait_for(
                        self.stream.await_output(), timeout=timeout
                    )
                    result = await output[1].receive()

                    if result.value and result.value.bytes_:
                        response_data = result.value.bytes_.decode("utf-8")
                        json_data = json.loads(response_data)
                        event_count += 1

                        if "event" in json_data:
                            event = json_data["event"]

                            if "contentStart" in event:
                                role = event["contentStart"].get("role", "?")
                                ctype = event["contentStart"].get("type", "?")
                                print(f"  📋 Content start: role={role}, type={ctype}")

                            elif "textOutput" in event:
                                text = event["textOutput"].get("content", "")
                                print(f"  📝 Text: {text}")

                            elif "audioOutput" in event:
                                audio = event["audioOutput"].get("content", "")
                                audio_bytes = base64.b64decode(audio)
                                print(f"  🔊 Audio: {len(audio_bytes)} bytes")

                            elif "contentEnd" in event:
                                print(f"  ✓ Content end")

                            elif "completionStart" in event:
                                print(f"  🚀 Completion started")

                            elif "completionEnd" in event:
                                print(f"  🏁 Completion ended")
                                break

                            else:
                                print(f"  ℹ️  Event: {list(event.keys())}")

                except asyncio.TimeoutError:
                    print(f"\n⏱️ Timeout after {timeout}s")
                    break

        except Exception as e:
            print(f"\n⚠️  Stream ended: {e}")

        print(f"\n📊 Total events received: {event_count}")
        return event_count


async def main():
    print("🎤 Testing Nova Sonic Bidirectional Streaming")
    print("=" * 60)
    print(f"Region: {os.getenv('AWS_REGION', 'us-east-1')}")
    print(f"Model: amazon.nova-sonic-v1:0")
    print()

    test = NovaSonicTest()

    try:
        # Start session
        await test.start_session()

        # Start processing responses in background
        response_task = asyncio.create_task(test.process_responses())

        # Send test audio
        await test.send_audio_and_get_response()

        # Wait for responses
        event_count = await response_task

        # End session
        await test.end_session()

        if event_count > 0:
            print("\n🎉 SUCCESS! Nova Sonic bidirectional streaming is working!")
        else:
            print("\n⚠️  No events received — check model access in AWS console")

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        print(f"Error type: {type(e).__name__}")
        
        error_msg = str(e)
        if "AccessDeniedException" in error_msg:
            print("\n💡 Check that your AWS credentials have Bedrock access")
            print("   and Nova Sonic model is enabled in your account")
        elif "ValidationException" in error_msg:
            print("\n💡 Model ID or request format issue")
        elif "ResourceNotFoundException" in error_msg:
            print("\n💡 Model not available in this region")
            print("   Nova Sonic is available in: us-east-1, us-west-2, ap-northeast-1, eu-north-1")


if __name__ == "__main__":
    asyncio.run(main())
