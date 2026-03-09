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
        # Use Tokyo region for Nova 2 Sonic (only available there)
        self.region = os.getenv('AWS_REGION_VOICE', 'ap-northeast-1')
        self.model_id = os.getenv('BEDROCK_NOVA_SONIC_MODEL_ID', 'amazon.nova-2-sonic-v1:0')
        self.language = os.getenv('VOICE_LANGUAGE', 'hi-IN')
        self.sessions: Dict[str, Dict] = {}
        self._client: Optional[BedrockRuntimeClient] = None

        logger.info(f"Nova 2 Sonic Service: model={self.model_id}, region={self.region}")

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
                "You are a Hindi/Hinglish voice transcription assistant for a shopping app in India.\n\n"
                "CRITICAL TRANSCRIPTION RULES:\n"
                "1. ALWAYS transcribe user speech in Hindi/Hinglish (romanized Hindi), NEVER translate to English\n"
                "2. 'do kardo' must be transcribed as 'do kardo', NOT 'let's keep the same amount'\n"
                "3. 'chaar aur add kardo' must stay as 'chaar aur add kardo', NOT 'add four more'\n"
                "4. Hindi numbers: ek, do, teen, char/chaar, paanch — transcribe as spoken\n"
                "5. Brand names and product names in English stay in English (e.g., 'Amul', 'Milk')\n"
                "6. Keep mixed Hindi-English as-is: 'milk do packet add kardo'\n"
                "7. NEVER interpret, translate, or rephrase — just transcribe exactly what the user says\n\n"
                "If user speaks in Hindi, output Hindi (romanized). If user speaks in English, output English.\n"
                "You are a shopkeeper assistant. Keep any responses SHORT (1-2 sentences) in Hindi.\n"
                "Use 'Sir' and 'ji' respectfully."
            )
        else:
            # Store owner persona - TRANSCRIPTION ONLY, NO RESPONSES
            system_prompt = (
                "You are a voice transcription service for a store management system in India.\n\n"
                "YOUR ONLY JOB: Transcribe user speech accurately in Hindi/Hinglish (romanized).\n\n"
                "CRITICAL RULES:\n"
                "1. ONLY transcribe what the user says - DO NOT generate responses\n"
                "2. DO NOT answer questions, provide advice, or give instructions\n"
                "3. DO NOT say anything like 'I can help you', 'follow these steps', etc.\n"
                "4. Transcribe Hindi in romanized form: 'aaj ka stock' not 'today's stock'\n"
                "5. Keep numbers as spoken: 'do', 'teen', 'char' (not 2, 3, 4)\n"
                "6. If you must respond, say ONLY: 'Ji sir' (nothing more)\n\n"
                "Remember: You are ONLY a transcription service. All responses are handled by another system."
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

        # Support both customer context (available_products) and store context (inventory)
        products = context.get('available_products', context.get('inventory', []))
        if not products:
            return

        # For store context, include more detailed inventory information
        is_store_context = 'inventory' in context
        
        products_list = []
        for p in products[:50]:  # Increased from 20 to 50 for store owners
            if is_store_context:
                # Store owner needs detailed stock info
                products_list.append(
                    f"- {p.get('name')} ({p.get('brand', 'Local')}) - ₹{p.get('price')} "
                    f"[Stock: {p.get('stock', 0)} units, Category: {p.get('category', 'General')}]"
                )
            else:
                # Customer needs simpler product list
                products_list.append(
                    f"- {p.get('name')} ({p.get('brand', 'Local')}) - ₹{p.get('price')} "
                    f"[stock: {p.get('stock', 0)}]"
                )

        if is_store_context:
            # Store owner context
            store_info = context.get('store_info', {})
            analytics = context.get('analytics', {})
            sales_data = context.get('sales_data', {})
            
            context_text = f"""STORE INVENTORY AND ANALYTICS:

Store: {store_info.get('name', 'Your Store')}
Total Products: {len(products)}
Low Stock Items: {analytics.get('low_stock_count', 0)}
Today's Revenue: ₹{sales_data.get('total_revenue', 0)}
Today's Orders: {sales_data.get('total_orders', 0)}

COMPLETE INVENTORY LIST:
{chr(10).join(products_list)}

You are a helpful store management assistant. Answer questions about inventory, stock levels, sales, and provide business insights based on this data."""
        else:
            # Customer context
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
        
        context_type = "store inventory" if is_store_context else "customer products"
        logger.info(f"Sent {context_type} context ({len(products)} products) to Nova Sonic session {session_id}")

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
