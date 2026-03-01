from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from app.services.nova_sonic_service import NovaSonicService
from app.services.voice_context_service import VoiceContextService
import json
import asyncio
import re
import logging
import httpx
import base64
import os

router = APIRouter()
logger = logging.getLogger(__name__)


def parse_cart_action_from_transcript(text: str, products: list) -> dict | None:
    """
    Parse AI assistant transcript for cart add/remove intent.
    Matches product names from context and extracts quantity.
    
    Returns: {action, product, quantity} or None
    """
    text_lower = text.lower().strip()
    
    # Cart-add intent keywords (Hindi/Hinglish/English)
    add_keywords = [
        'add ho gaya', 'add kar diya', 'add kiya', 'cart mein',
        'daal diya', 'dal diya', 'add ho gaye', 'add kar diye',
        'added', 'add ho', 'jod diya', 'rakh diya',
        'packet cart', 'cart me', 'add karta', 'add karti',
    ]
    
    is_add = any(kw in text_lower for kw in add_keywords)
    if not is_add:
        return None
    
    # Extract quantity (Hindi numbers)
    quantity = 1.0
    hindi_numbers = {
        'ek': 1, 'do': 2, 'teen': 3, 'char': 4, 'paanch': 5,
        'panch': 5, 'cheh': 6, 'saat': 7, 'aath': 8, 'nau': 9, 'das': 10,
        'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
    }
    
    for word, num in hindi_numbers.items():
        if word in text_lower.split():
            quantity = float(num)
            break
    
    # Also check for digit numbers
    digit_match = re.search(r'(\d+)\s*(packet|piece|kg|litre|liter)', text_lower)
    if digit_match:
        quantity = float(digit_match.group(1))
    
    # Match product from context
    best_match = None
    best_score = 0
    
    for product in products:
        product_name = product.get('name', '').lower()
        product_words = set(product_name.split())
        text_words = set(text_lower.split())
        
        # Check how many product name words appear in the transcript
        matching_words = product_words & text_words
        if len(matching_words) > 0:
            score = len(matching_words) / len(product_words) if product_words else 0
            
            # Bonus for exact substring match
            if product_name in text_lower:
                score += 1.0
            
            # Also check brand
            brand = product.get('brand', '').lower()
            if brand and brand in text_lower:
                score += 0.5
            
            if score > best_score:
                best_score = score
                best_match = product
    
    if best_match and best_score >= 0.3:
        logger.info(f"🛒 Cart action: ADD {quantity}x {best_match['name']} (score: {best_score:.2f})")
        return {
            'action': 'add',
            'product': best_match,
            'quantity': quantity,
        }
    
    return None


async def generate_sarvam_tts(text: str) -> bytes | None:
    """Generate high-quality Hindi TTS using Sarvam AI API"""
    url = "https://api.sarvam.ai/text-to-speech"
    api_key = os.getenv("SARVAM_API_KEY")
    if not api_key:
        logger.error("SARVAM_API_KEY environment variable is missing")
        return None

    headers = {
        "api-subscription-key": api_key,
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
        try:
            response = await client.post(url, json=payload, headers=headers, timeout=10.0)
            if response.status_code == 200:
                data = response.json()
                if data.get('audios') and len(data['audios']) > 0:
                    wav_data = base64.b64decode(data['audios'][0])
                    # Return the full base64 decoded WAV data directly
                    return wav_data
            else:
                logger.error(f"Sarvam API error: {response.text}")
        except Exception as e:
            logger.error(f"Sarvam TTS error: {e}")
            
    return None

@router.websocket("/ws/voice/customer/{user_id}")
async def customer_voice_assistant(
    websocket: WebSocket,
    user_id: str,
    latitude: float = Query(..., description="User's latitude"),
    longitude: float = Query(..., description="User's longitude")
):
    """
    Real-time voice assistant for NukkadMart customers
    Handles bidirectional audio streaming with Nova Sonic
    """
    await websocket.accept()
    logger.info(f"Customer voice session started for user: {user_id} at ({latitude}, {longitude})")
    
    nova_sonic = NovaSonicService()
    context_service = VoiceContextService()
    
    # Initialize session with "Helpful Shopkeeper" persona
    session = await nova_sonic.create_session(
        user_id=user_id,
        persona="helpful_shopkeeper",
        tools=[
            "check_inventory",
            "add_to_cart",
            "get_cart",
            "suggest_alternatives",
            "compare_brands",
            "calculate_quantity_match",
            "remove_from_cart"
        ]
    )
    
    session_id = session['id']
    context_products = []  # Products from context for cart matching
    
    # Pre-load context: nearby stores + inventory
    try:
        context_summary = await context_service.initialize_customer_context(
            session_id=session_id,
            user_id=user_id,
            latitude=latitude,
            longitude=longitude,
            radius_km=10.0
        )
        
        await websocket.send_text(json.dumps({
            'event': 'context_loaded',
            'data': context_summary
        }))
        
        logger.info(f"Context loaded: {context_summary['stores_count']} stores, {context_summary['products_count']} products")
    except Exception as e:
        logger.error(f"Error loading context: {str(e)}")
        await websocket.send_text(json.dumps({
            'event': 'error',
            'message': 'Failed to load nearby stores'
        }))
    
    # Send context to Nova Sonic and keep product list for cart matching
    try:
        context = await context_service.get_context(session_id)
        if context:
            await nova_sonic.send_context(session_id, context)
            context_products = context.get('available_products', [])
            logger.info(f"Context sent to Nova Sonic ({len(context_products)} products for cart matching)")
    except Exception as e:
        logger.error(f"Error sending context to Nova Sonic: {e}")
        
    # Send initial welcome message TTS
    try:
        welcome_pcm = await generate_sarvam_tts("Namaste! Bataiye aapko kya chahiye?")
        if welcome_pcm:
            await websocket.send_bytes(welcome_pcm)
    except Exception as e:
        logger.error(f"Error sending welcome TTS: {e}")
    
    # Background response processing
    response_queue = asyncio.Queue()
    
    async def process_responses():
        try:
            async for response in nova_sonic.receive_responses(session_id):
                await response_queue.put(response)
        except Exception as e:
            logger.error(f"Response processing error: {e}")
            await response_queue.put(None)
    
    response_task = asyncio.create_task(process_responses())
    
    async def forward_responses():
        """Forward responses + intercept AI transcripts for cart actions"""
        try:
            while True:
                response = await response_queue.get()
                if response is None:
                    break
                    
                if response['type'] == 'audio_output':
                    # Drop Nova Sonic's robotic audio chunks
                    pass
                elif response['type'] == 'transcript':
                    # Forward transcript
                    await websocket.send_text(json.dumps({
                        'event': 'transcript',
                        'text': response['text'],
                        'is_user': response.get('is_user', False)
                    }))
                    
                    if not response.get('is_user', False):
                        # 1. Generate and send high-quality Sarvam TTS audio
                        pcm_audio = await generate_sarvam_tts(response['text'])
                        if pcm_audio:
                            # Send the full audio chunk down to Flutter
                            await websocket.send_bytes(pcm_audio)
                            
                        # 2. Check AI transcripts for cart add/remove actions
                        if context_products:
                            cart_action = parse_cart_action_from_transcript(
                                response['text'], context_products
                            )
                            if cart_action:
                                product = cart_action['product']
                                store_id = product.get('store_id', '')
                                
                                # Send cart_update to Flutter
                                await websocket.send_text(json.dumps({
                                    'event': 'cart_update',
                                    'action': 'add',
                                    'store_id': store_id,
                                    'quantity': cart_action['quantity'],
                                    'product': {
                                        'product_id': product.get('id', product.get('product_id', '')),
                                        'store_id': store_id,
                                        'name': product.get('name', ''),
                                        'category': product.get('category', 'General'),
                                        'brand': product.get('brand'),
                                        'price': product.get('price', 0),
                                        'unit': product.get('weight', product.get('unit')),
                                        'stock_quantity': product.get('stock', 0),
                                        'image_url': product.get('image_url'),
                                        'tags': product.get('tags', []),
                                    }
                                }))
                                logger.info(f"🛒 Sent cart_update: {cart_action['quantity']}x {product['name']}")
        except Exception as e:
            logger.error(f"Response forwarding error: {e}")
    
    forward_task = asyncio.create_task(forward_responses())
    
    # Audio streaming
    audio_started = False
    
    try:
        while True:
            data = await websocket.receive()
            
            if 'bytes' in data:
                audio_chunk = data['bytes']
                if not audio_started:
                    await nova_sonic.start_audio_input(session_id)
                    audio_started = True
                await nova_sonic.send_audio_chunk(session_id, audio_chunk)
            
            elif 'text' in data:
                try:
                    message = json.loads(data['text'])
                    if message.get('event') == 'end_audio':
                        if audio_started:
                            await nova_sonic.end_audio_input(session_id)
                            audio_started = False
                    elif message.get('event') == 'start_audio':
                        if not audio_started:
                            await nova_sonic.start_audio_input(session_id)
                            audio_started = True
                except json.JSONDecodeError:
                    pass
                
    except WebSocketDisconnect:
        logger.info(f"Customer voice session ended for user: {user_id}")
    except Exception as e:
        logger.error(f"Error in customer voice session: {str(e)}")
    finally:
        if audio_started:
            try:
                await nova_sonic.end_audio_input(session_id)
            except Exception:
                pass
        
        response_task.cancel()
        forward_task.cancel()
        await nova_sonic.close_session(session_id)
        await context_service.cleanup_context(session_id)
        
        try:
            await websocket.close()
        except Exception:
            pass


@router.websocket("/ws/voice/store/{store_id}")
async def store_voice_assistant(websocket: WebSocket, store_id: str):
    """Voice assistant for NukkadStore owners"""
    await websocket.accept()
    logger.info(f"Store voice session started for store: {store_id}")
    
    nova_sonic = NovaSonicService()
    context_service = VoiceContextService()
    
    session = await nova_sonic.create_session(
        user_id=store_id,
        persona="personal_manager",
        tools=["get_sales_report", "get_inventory_status", "get_low_stock_alerts",
               "suggest_pricing", "forecast_demand", "get_revenue_analytics",
               "get_top_products", "get_daily_summary"]
    )
    
    session_id = session['id']
    
    try:
        context_summary = await context_service.initialize_store_context(
            session_id=session_id, store_id=store_id
        )
        await websocket.send_text(json.dumps({
            'event': 'context_loaded', 'data': context_summary
        }))
    except Exception as e:
        logger.error(f"Error loading store context: {str(e)}")
    
    response_queue = asyncio.Queue()
    
    async def process_responses():
        try:
            async for response in nova_sonic.receive_responses(session_id):
                await response_queue.put(response)
        except Exception as e:
            logger.error(f"Response processing error: {e}")
            await response_queue.put(None)
    
    response_task = asyncio.create_task(process_responses())
    
    async def forward_responses():
        try:
            while True:
                response = await response_queue.get()
                if response is None:
                    break
                if response['type'] == 'audio_output':
                    # Drop Nova Sonic's robotic audio chunks
                    pass
                elif response['type'] in ('transcript', 'transcription'):
                    await websocket.send_text(json.dumps({
                        'event': 'transcript',
                        'text': response['text'],
                        'is_user': response.get('is_user', False)
                    }))
                    
                    if not response.get('is_user', False):
                        # Generate and send high-quality Sarvam TTS audio
                        pcm_audio = await generate_sarvam_tts(response['text'])
                        if pcm_audio:
                            await websocket.send_bytes(pcm_audio)
        except Exception as e:
            logger.error(f"Response forwarding error: {e}")
    
    forward_task = asyncio.create_task(forward_responses())
    audio_started = False
    
    try:
        while True:
            data = await websocket.receive()
            if 'bytes' in data:
                if not audio_started:
                    await nova_sonic.start_audio_input(session_id)
                    audio_started = True
                await nova_sonic.send_audio_chunk(session_id, data['bytes'])
            elif 'text' in data:
                try:
                    message = json.loads(data['text'])
                    if message.get('event') == 'end_audio' and audio_started:
                        await nova_sonic.end_audio_input(session_id)
                        audio_started = False
                    elif message.get('event') == 'start_audio' and not audio_started:
                        await nova_sonic.start_audio_input(session_id)
                        audio_started = True
                except json.JSONDecodeError:
                    pass
    except WebSocketDisconnect:
        logger.info(f"Store voice session ended for store: {store_id}")
    except Exception as e:
        logger.error(f"Error in store voice session: {str(e)}")
    finally:
        if audio_started:
            try:
                await nova_sonic.end_audio_input(session_id)
            except Exception:
                pass
        response_task.cancel()
        forward_task.cancel()
        await nova_sonic.close_session(session_id)
        await context_service.cleanup_context(session_id)
        try:
            await websocket.close()
        except Exception:
            pass
