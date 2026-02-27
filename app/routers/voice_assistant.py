from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.services.nova_sonic_service import NovaSonicService
import json
import asyncio
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

@router.websocket("/ws/voice/customer/{user_id}")
async def customer_voice_assistant(websocket: WebSocket, user_id: str):
    """
    Real-time voice assistant for NukkadMart customers
    Handles bidirectional audio streaming with Nova Sonic
    """
    await websocket.accept()
    logger.info(f"Customer voice session started for user: {user_id}")
    
    nova_sonic = NovaSonicService()
    
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
    
    try:
        while True:
            # Receive audio chunk from Flutter app
            data = await websocket.receive_bytes()
            
            # Stream to Nova Sonic and get response
            async for response in nova_sonic.stream_conversation(
                session_id=session['id'],
                audio_input=data
            ):
                if response['type'] == 'audio':
                    # Send AI audio response back to Flutter
                    await websocket.send_bytes(response['data'])
                
                elif response['type'] == 'cart_update':
                    # Send cart update as JSON
                    await websocket.send_text(json.dumps({
                        'event': 'cart_update',
                        'cart': response['cart']
                    }))
                
    except WebSocketDisconnect:
        logger.info(f"Customer voice session ended for user: {user_id}")
        await nova_sonic.close_session(session['id'])
    except Exception as e:
        logger.error(f"Error in customer voice session: {str(e)}")
        await websocket.close()


@router.websocket("/ws/voice/store/{store_id}")
async def store_voice_assistant(websocket: WebSocket, store_id: str):
    """
    Real-time voice assistant for NukkadStore owners
    Provides analytics, reports, and business insights
    """
    await websocket.accept()
    logger.info(f"Store voice session started for store: {store_id}")
    
    nova_sonic = NovaSonicService()
    
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
    
    try:
        while True:
            # Receive audio chunk from Flutter app
            data = await websocket.receive_bytes()
            
            # Stream to Nova Sonic and get response
            async for response in nova_sonic.stream_conversation(
                session_id=session['id'],
                audio_input=data
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
                
    except WebSocketDisconnect:
        logger.info(f"Store voice session ended for store: {store_id}")
        await nova_sonic.close_session(session['id'])
    except Exception as e:
        logger.error(f"Error in store voice session: {str(e)}")
        await websocket.close()
