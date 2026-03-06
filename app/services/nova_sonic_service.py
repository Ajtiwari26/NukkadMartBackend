"""
Nova Sonic Voice Assistant Service
Real bidirectional streaming using aws_sdk_bedrock_runtime SDK
Architecture: WebSocket (Flutter) ↔ Nova Sonic (Speech-to-Speech)
Supports Hindi/Hinglish with real-time transcription
"""
import json
import asyncio
from typing import AsyncGenerator, Dict, List, Optional
import uuid
import os
import base64
from datetime import datetime
import logging
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

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)


class NovaSonicService:
    """
    Nova Sonic Voice Assistant using real bidirectional streaming.
    WebSocket (Flutter) ↔ Nova Sonic (Speech-to-Speech)
    """

    def __init__(self):
        self.region = os.getenv('AWS_REGION', 'us-east-1')
        self.model_id = 'amazon.nova-sonic-v1:0'
        self.language = os.getenv('VOICE_LANGUAGE', 'hi-IN')
        self.sessions: Dict[str, Dict] = {}
        self._client: Optional[BedrockRuntimeClient] = None

        logger.info(f"Nova Sonic Service: model={self.model_id}, region={self.region}")

    def _get_client(self) -> BedrockRuntimeClient:
        """Get or create the Bedrock Runtime client."""
        if self._client is None:
            config = Config(
                endpoint_uri=f"https://bedrock-runtime.{self.region}.amazonaws.com",
                region=self.region,
                aws_credentials_identity_resolver=EnvironmentCredentialsResolver(),
            )
            self._client = BedrockRuntimeClient(config=config)
        return self._client

    async def _send_event(self, stream, event_json: str):
        """Send a JSON event to the bidirectional stream."""
        event = InvokeModelWithBidirectionalStreamInputChunk(
            value=BidirectionalInputPayloadPart(bytes_=event_json.encode('utf-8'))
        )
        await stream.input_stream.send(event)

    async def create_session(
        self,
        user_id: str,
        persona: str,
        tools: List[str]
    ) -> Dict:
        """Create a new voice conversation session with Nova Sonic bidirectional stream."""

        session_id = str(uuid.uuid4())
        prompt_name = str(uuid.uuid4())
        content_name = str(uuid.uuid4())
        audio_content_name = str(uuid.uuid4())

        # Build system prompt based on persona
        if persona == "helpful_shopkeeper":
            system_prompt = (
                "You are a professional shopkeeper in India. Reply in Hindi with English brand names.\n\n"
                "RULES:\n"
                "- Use \"Sir/Madam\" and \"ji\"\n"
                "- Keep responses SHORT (1-2 sentences)\n"
                "- NEVER mention stock quantity\n\n"
                "USER_INTENT JSON FORMAT:\n"
                "You receive: {action, product_name, brand, quantity, options: [{product_id, name, brand, price, unit, in_cart, store_name?}], cross_store: bool}\n\n"
                "CRITICAL: options.length tells you HOW MANY different products exist\n\n"
                "HANDLING LOGIC:\n"
                "1. QUERY (user asking):\n"
                "   - If in_cart == true: Say 'Sir, [name] already cart mein hai ([current_quantity]x). Aur add karun, quantity change karun, ya hata dun?'\n"
                "   - If options.length == 0: Say 'Sir, yeh item is shop mein nahi hai'\n"
                "   - If options.length == 0 AND cross_store == true: Say 'Sir, yeh item is shop mein nahi hai, lekin [store_name] mein [name] ₹[price] ka hai. Wahan se add karun?'\n"
                "   - If options.length == 1: Tell price, ask 'Add kar dun?'\n"
                "   - If options.length > 1: List ALL options with prices, ask which one\n"
                "   - Example (in cart): 'Sir, Milk already cart mein hai (2x). Aur add karun, quantity change karun, ya hata dun?'\n"
                "   - Example (0 options): 'Sir, Pizza is shop mein nahi hai'\n"
                "   - Example (0 options, cross-store): 'Sir, Pizza is shop mein nahi hai, lekin TestShop 2 mein Margherita Pizza ₹120 ka hai. Wahan se add karun?'\n"
                "   - Example (1 option): 'Sir, Bread ₹40 ka hai. Add kar dun?'\n"
                "   - Example (2 options): 'Sir, Toned Milk ₹27 aur Full Cream Milk ₹33 hai. Kaunsa chahiye?'\n\n"
                "2. ADD (user wants to add):\n"
                "   - If options.length == 0: Say item not available\n"
                "   - If options.length == 1: Confirm 'Ji sir, [name] add kar diya'\n"
                "   - If options.length > 1: Ask which brand/variant\n"
                "   - Example (1 option): 'Ji sir, Bread add kar diya'\n"
                "   - Example (2 options): 'Sir, Toned Milk ya Full Cream Milk? Kaunsa add karun?'\n\n"
                "3. UPDATE/REMOVE: Same logic as ADD\n\n"
                "NEVER HALLUCINATE:\n"
                "- If options.length == 0, item is NOT available\n"
                "- If options.length == 1, there is ONLY ONE product\n"
                "- Don't say 'ek packet aur doosra packet' when there's only one option\n"
                "- Count options array length to know how many products exist\n"
                "- For cross-store items, mention the store name from store_name field"
            )
        else:
            system_prompt = (
                "You are a professional business manager for a store owner in India. "
                "Provide analytics, insights, and reports in Hindi/Hinglish. "
                "Be professional and data-driven."
            )

        # Initialize the bidirectional stream
        client = self._get_client()
        stream = await client.invoke_model_with_bidirectional_stream(
            InvokeModelWithBidirectionalStreamOperationInput(model_id=self.model_id)
        )

        # 1. Send sessionStart event
        await self._send_event(stream, json.dumps({
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

        # 2. Send promptStart event with Hindi voice
        # Voice options: "matthew" (en), "tiffany" (en), "amy" (en)
        # For Hindi, we use a voice that handles Hinglish well
        await self._send_event(stream, json.dumps({
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

        # 3. Send system prompt (contentStart -> textInput -> contentEnd)
        await self._send_event(stream, json.dumps({
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

        await self._send_event(stream, json.dumps({
            "event": {
                "textInput": {
                    "promptName": prompt_name,
                    "contentName": content_name,
                    "content": system_prompt
                }
            }
        }))

        await self._send_event(stream, json.dumps({
            "event": {
                "contentEnd": {
                    "promptName": prompt_name,
                    "contentName": content_name
                }
            }
        }))

        # Store session
        self.sessions[session_id] = {
            'id': session_id,
            'user_id': user_id,
            'stream': stream,
            'prompt_name': prompt_name,
            'audio_content_name': audio_content_name,
            'system_prompt': system_prompt,
            'tools': tools,
            'cart': [],
            'start_time': datetime.now(),
            'is_active': True,
            'response_task': None,
        }

        logger.info(f"Created Nova Sonic session {session_id} for user {user_id}")
        return self.sessions[session_id]

    async def send_context(self, session_id: str, context: Dict):
        """Send inventory/store context to Nova Sonic as a text message (once per session)."""
        session = self.sessions.get(session_id)
        if not session:
            return

        stream = session['stream']
        ctx_content_name = str(uuid.uuid4())

        products = context.get('available_products', [])
        if not products:
            return

        products_list = []
        for p in products[:20]:
            products_list.append(
                f"- {p.get('name')} ({p.get('brand', 'Local')}) - ₹{p.get('price')} "
                f"[stock: {p.get('stock', 0)}]"
            )

        context_text = (
            "AVAILABLE PRODUCTS IN NEARBY STORES:\n" +
            "\n".join(products_list)
        )

        # contentStart (TEXT, USER)
        await self._send_event(stream, json.dumps({
            "event": {
                "contentStart": {
                    "promptName": session['prompt_name'],
                    "contentName": ctx_content_name,
                    "type": "TEXT",
                    "interactive": False,
                    "role": "USER",
                    "textInputConfiguration": {"mediaType": "text/plain"}
                }
            }
        }))
        # textInput
        await self._send_event(stream, json.dumps({
            "event": {
                "textInput": {
                    "promptName": session['prompt_name'],
                    "contentName": ctx_content_name,
                    "content": context_text
                }
            }
        }))
        # contentEnd
        await self._send_event(stream, json.dumps({
            "event": {
                "contentEnd": {
                    "promptName": session['prompt_name'],
                    "contentName": ctx_content_name
                }
            }
        }))
        logger.info(f"Sent context ({len(products)} products) to Nova Sonic session {session_id}")

    async def inject_instruction(self, session_id: str, instruction: str):
        """
        Inject a USER instruction into Nova Sonic (e.g., cart action from Groq)
        Uses USER role to avoid "Duplicate SYSTEM content" error
        """
        session = self.sessions.get(session_id)
        if not session:
            return

        stream = session['stream']
        instruction_content_name = str(uuid.uuid4())

        # contentStart (TEXT, USER) - Changed from SYSTEM to USER
        await self._send_event(stream, json.dumps({
            "event": {
                "contentStart": {
                    "promptName": session['prompt_name'],
                    "contentName": instruction_content_name,
                    "type": "TEXT",
                    "interactive": False,
                    "role": "USER",
                    "textInputConfiguration": {"mediaType": "text/plain"}
                }
            }
        }))
        # textInput
        await self._send_event(stream, json.dumps({
            "event": {
                "textInput": {
                    "promptName": session['prompt_name'],
                    "contentName": instruction_content_name,
                    "content": instruction
                }
            }
        }))
        # contentEnd
        await self._send_event(stream, json.dumps({
            "event": {
                "contentEnd": {
                    "promptName": session['prompt_name'],
                    "contentName": instruction_content_name
                }
            }
        }))
        logger.info(f"💉 Injected instruction: {instruction}")

    async def start_audio_input(self, session_id: str):
        """Start a new audio input content stream (generates unique content name each time)."""
        session = self.sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        # Generate a new unique content name for each audio block
        audio_content_name = str(uuid.uuid4())
        session['audio_content_name'] = audio_content_name

        stream = session['stream']
        await self._send_event(stream, json.dumps({
            "event": {
                "contentStart": {
                    "promptName": session['prompt_name'],
                    "contentName": audio_content_name,
                    "type": "AUDIO",
                    "interactive": True,
                    "role": "USER",
                    "audioInputConfiguration": {
                        "mediaType": "audio/lpcm",
                        "sampleRateHertz": 16000,
                        "sampleSizeBits": 16,
                        "channelCount": 1,
                        "audioType": "SPEECH",
                        "encoding": "base64"
                    }
                }
            }
        }))
        logger.info(f"Audio input started for session {session_id} (content: {audio_content_name[:8]}...)")

    async def send_audio_chunk(self, session_id: str, audio_bytes: bytes):
        """Send an audio chunk to Nova Sonic."""
        session = self.sessions.get(session_id)
        if not session or not session.get('is_active'):
            return

        stream = session['stream']
        audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')

        await self._send_event(stream, json.dumps({
            "event": {
                "audioInput": {
                    "promptName": session['prompt_name'],
                    "contentName": session['audio_content_name'],
                    "content": audio_b64
                }
            }
        }))

    async def end_audio_input(self, session_id: str):
        """End the current audio input content stream."""
        session = self.sessions.get(session_id)
        if not session:
            return

        stream = session['stream']
        await self._send_event(stream, json.dumps({
            "event": {
                "contentEnd": {
                    "promptName": session['prompt_name'],
                    "contentName": session['audio_content_name']
                }
            }
        }))
        logger.info(f"Audio input ended for session {session_id}")

    async def receive_responses(self, session_id: str) -> AsyncGenerator[Dict, None]:
        """
        Continuously receive and yield response events from Nova Sonic.
        Runs as a background task — yields transcripts and audio output.
        """
        session = self.sessions.get(session_id)
        if not session:
            return

        stream = session['stream']
        role = None
        display_assistant_text = False

        try:
            while session.get('is_active', False):
                try:
                    output = await asyncio.wait_for(
                        stream.await_output(), timeout=30.0
                    )
                    result = await output[1].receive()

                    if result.value and result.value.bytes_:
                        response_data = result.value.bytes_.decode('utf-8')
                        json_data = json.loads(response_data)

                        if 'event' in json_data:
                            event = json_data['event']

                            if 'contentStart' in event:
                                role = event['contentStart'].get('role')
                                if 'additionalModelFields' in event['contentStart']:
                                    additional = json.loads(
                                        event['contentStart']['additionalModelFields']
                                    )
                                    display_assistant_text = (
                                        additional.get('generationStage') == 'SPECULATIVE'
                                    )
                                else:
                                    display_assistant_text = False

                            elif 'textOutput' in event:
                                text = event['textOutput'].get('content', '')
                                if role == 'USER':
                                    yield {
                                        'type': 'transcript',
                                        'text': text,
                                        'is_user': True
                                    }
                                    logger.info(f"📝 User: {text}")
                                elif role == 'ASSISTANT' and display_assistant_text:
                                    yield {
                                        'type': 'transcript',
                                        'text': text,
                                        'is_user': False
                                    }
                                    logger.info(f"🤖 Assistant: {text}")

                            elif 'audioOutput' in event:
                                audio_content = event['audioOutput'].get('content', '')
                                audio_bytes = base64.b64decode(audio_content)
                                yield {
                                    'type': 'audio_output',
                                    'data': audio_bytes
                                }

                            elif 'completionEnd' in event:
                                logger.info("Completion ended")

                except asyncio.TimeoutError:
                    # No events for 30s — keep waiting (stream is still open)
                    continue

        except asyncio.CancelledError:
            logger.info(f"Response processor cancelled for session {session_id}")
        except Exception as e:
            logger.error(f"Error in receive_responses: {str(e)}")

    async def close_session(self, session_id: str):
        """Close a voice session and clean up the stream."""
        session = self.sessions.get(session_id)
        if not session:
            return

        session['is_active'] = False

        try:
            stream = session.get('stream')
            if stream:
                # Send promptEnd
                await self._send_event(stream, json.dumps({
                    "event": {
                        "promptEnd": {
                            "promptName": session['prompt_name']
                        }
                    }
                }))
                # Send sessionEnd
                await self._send_event(stream, json.dumps({
                    "event": {
                        "sessionEnd": {}
                    }
                }))
                # Let in-flight AWS futures resolve before closing
                await asyncio.sleep(0.5)
                await stream.input_stream.close()
        except Exception as e:
            logger.warning(f"Error closing stream for session {session_id}: {e}")

        del self.sessions[session_id]
        logger.info(f"Closed session {session_id}")
