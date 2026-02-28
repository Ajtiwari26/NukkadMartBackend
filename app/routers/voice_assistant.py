from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from app.services.nova_sonic_service import NovaSonicService
from app.services.voice_context_service import VoiceContextService
import json
import asyncio
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

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
    Loads nearby stores and inventory from database into Redis
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
    
    # Pre-load context: nearby stores + inventory into Redis (ONE TIME)
    try:
        context_summary = await context_service.initialize_customer_context(
            session_id=session['id'],
            user_id=user_id,
            latitude=latitude,
            longitude=longitude,
            radius_km=10.0
        )
        
        # Send context summary to Flutter
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
    
    try:
        while True:
            # Receive data from Flutter app
            data = await websocket.receive()
            
            # Handle audio data (bytes)
            if 'bytes' in data:
                audio_chunk = data['bytes']
                
                # Get context from Redis
                context = await context_service.get_context(session['id'])
                
                # Stream to hybrid pipeline
                async for response in nova_sonic.stream_conversation(
                    session_id=session['id'],
                    audio_input=audio_chunk,
                    context=context
                ):
                    if response['type'] == 'audio_output':
                        # Send AI audio back to Flutter (MP3 format)
                        await websocket.send_bytes(response['data'])
                    
                    elif response['type'] == 'transcript':
                        # Send transcript (user or AI)
                        await websocket.send_text(json.dumps({
                            'event': 'transcript',
                            'text': response['text'],
                            'is_user': response.get('is_user', False)
                        }))
                
    except WebSocketDisconnect:
        logger.info(f"Customer voice session ended for user: {user_id}")
        await nova_sonic.close_session(session['id'])
        await context_service.cleanup_context(session['id'])
    except Exception as e:
        logger.error(f"Error in customer voice session: {str(e)}")
        await context_service.cleanup_context(session['id'])
        await websocket.close()


@router.websocket("/ws/voice/store/{store_id}")
async def store_voice_assistant(websocket: WebSocket, store_id: str):
    """
    Real-time voice assistant for NukkadStore owners
    Provides analytics, reports, and business insights
    Pre-loads store data and analytics in Redis for fast access
    """
    await websocket.accept()
    logger.info(f"Store voice session started for store: {store_id}")
    
    nova_sonic = NovaSonicService()
    context_service = VoiceContextService()
    
    # Initialize session with "Personal Manager" persona
    session = await nova_sonic.create_session(
        user_id=store_id,
        persona="personal_manager",
        tools=[
            "get_sales_report",
            "get_inventory_status",
            "get_low_stock_alerts",
            "suggest_pricing",
            "forecast_demand",
            "get_revenue_analytics",
            "get_top_products",
            "get_daily_summary"
        ]
    )
    
    # Pre-load context: store data + analytics into Redis
    try:
        context_summary = await context_service.initialize_store_context(
            session_id=session['id'],
            store_id=store_id
        )
        
        # Send context summary to Flutter
        await websocket.send_text(json.dumps({
            'event': 'context_loaded',
            'data': context_summary
        }))
        
        logger.info(f"Store context loaded: {context_summary['total_products']} products, ₹{context_summary['today_revenue']} revenue")
    except Exception as e:
        logger.error(f"Error loading store context: {str(e)}")
        await websocket.send_text(json.dumps({
            'event': 'error',
            'message': 'Failed to load store data'
        }))
    
    try:
        while True:
            # Receive audio chunk from Flutter app
            data = await websocket.receive_bytes()
            
            # Stream to Nova Sonic and get response
            # Nova Sonic will use context_service for fast data access
            async for response in nova_sonic.stream_conversation(
                session_id=session['id'],
                audio_input=data,
                context_service=context_service  # Pass context service
            ):
                if response['type'] == 'audio':
                    # Send AI audio response back to Flutter
                    await websocket.send_bytes(response['data'])
                
                elif response['type'] == 'insight':
                    # Send business insight as JSON
                    await websocket.send_text(json.dumps({
                        'event': 'insight',
                        'data': response['data']
                    }))
                
                elif response['type'] == 'transcription':
                    # Send transcription for display
                    await websocket.send_text(json.dumps({
                        'event': 'transcription',
                        'text': response['text'],
                        'is_user': response.get('is_user', False)
                    }))
                
    except WebSocketDisconnect:
        logger.info(f"Store voice session ended for store: {store_id}")
        await nova_sonic.close_session(session['id'])
        await context_service.cleanup_context(session['id'])
    except Exception as e:
        logger.error(f"Error in store voice session: {str(e)}")
        await context_service.cleanup_context(session['id'])
        await websocket.close()
