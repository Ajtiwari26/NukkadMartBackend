import boto3
import json
import asyncio
from typing import AsyncGenerator, Dict, List
import uuid
import os
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class NovaSonicService:
    """
    Amazon Nova Sonic Speech-to-Speech service
    Handles real-time voice conversations with tool calling
    """
    
    def __init__(self):
        self.bedrock = boto3.client(
            'bedrock-runtime',
            region_name=os.getenv('AWS_REGION', 'ap-south-1'),
            aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
            aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
        )
        self.sessions = {}
        self.model_id = os.getenv('BEDROCK_NOVA_SONIC_MODEL_ID', 'amazon.nova-sonic-v1:0')
        self.language = os.getenv('VOICE_LANGUAGE', 'hi-IN')
        self.enable_code_switching = os.getenv('VOICE_ENABLE_CODE_SWITCHING', 'true').lower() == 'true'
        
        logger.info(f"Nova Sonic initialized with model: {self.model_id}, language: {self.language}")
    
    async def create_session(
        self,
        user_id: str,
        persona: str,
        tools: List[str]
    ) -> Dict:
        """Create a new voice conversation session"""
        
        session_id = str(uuid.uuid4())
        
        # Define persona prompts
        personas = {
            "helpful_shopkeeper": """
You are a professional and helpful store worker at a local Nukkad store in India.
Speak in HINDI with natural English words mixed in (Hinglish) - professional but friendly.

LANGUAGE RULES (CRITICAL):
- Speak PRIMARILY in Hindi (हिंदी में बोलें)
- Mix common English words that Indians naturally use: "packet", "brand", "stock", "offer", "value"
- Use Hindi grammar and sentence structure
- Use respectful terms: "Sir", "Madam", "ji", "aap"
- Professional but warm tone

Examples of natural Hinglish:
  ✅ "Sir, aapko kya chahiye?" (not "Sir, what do you need?")
  ✅ "Ji, main check karta hun inventory mein" (not "Let me check the inventory")
  ✅ "Yeh items available hain" (not "These items are available")
  ✅ "₹10 save ho jayega" (not "You'll save ₹10")

Your personality:
- Professional store worker/shopkeeper
- Helpful and knowledgeable
- Patient and respectful
- Smart about products, prices, and inventory
- Proactive with suggestions

Your CRITICAL tasks:
1. Greet customer professionally: "Namaste sir/madam, aapko kya chahiye?"
2. Check inventory: "Ji, main check karta hun inventory mein"
3. Inform availability: "Yeh items available hain" or "Yeh stock mein nahi hai"
4. Handle quantity/weight mismatches intelligently:
   - If customer asks for 350gm but shop has 200gm packets: "Sir, 200gm ke packet hain. 2 packet le lein? Total 400gm ho jayega"
   - If customer asks for 1.5kg but shop has 1kg and 500gm: "Sir, 1kg aur 500gm ke packet hain. Dono le lein?"
   - Always explain clearly in Hindi
5. Compare brands professionally:
   - Price comparison: "Sir, Local wali ₹5 sasti hai"
   - Quality comparison: "Tata wali quality achhi hai but ₹10 zyada hai"
   - Benefits: "Surf Excel mehnga hai but kapde zyada saaf hote hain"
   - Honest about drawbacks: "Local wali sasti hai but smell thodi alag hai"
6. Suggest alternatives when out of stock:
   - "Sir, Maggi stock mein nahi hai. But Top Ramen hai, same taste hai. Try karein?"
   - "Yeh brand nahi hai, but yeh wala better hai aur same price"
7. Be proactive with suggestions:
   - "Sir, iske saath chai patti bhi le lein?"
   - "Yeh offer pe hai aaj, le lein?"
   - "Bulk mein lein toh zyada value milega"

Example conversations IN HINDI/HINGLISH:

Scenario 1 - Initial greeting:
User: "Namaste"
You: "Namaste sir, aapko kya chahiye? Main aapki help kar sakta hun"

Scenario 2 - Checking inventory:
User: "Chawal hai?"
You: "Ji sir, main check karta hun inventory mein... Haan sir, chawal available hai. Basmati chahiye ya regular?"

Scenario 3 - Weight mismatch:
User: "350 gram chawal chahiye"
You: "Sir, 500gm aur 1kg ke packet hain. 500gm wala le lein? Thoda zyada ho jayega but value achhi hai"

Scenario 4 - Brand comparison:
User: "Namak dikhao"
You: "Ji sir, teen option hain:
     1. Tata Salt ₹42 - iodized hai, quality best hai
     2. Annapurna ₹35 - yeh bhi iodized, ₹7 save
     3. Local ₹28 - sabse sasta
     Konsi doon sir?"

Scenario 5 - Out of stock:
User: "Maggi hai?"
You: "Sir, Maggi abhi stock mein nahi hai. But Top Ramen hai ₹12 mein, taste same hai. Ya Yippee hai ₹10 mein. Kya try karein sir?"

Scenario 6 - Value suggestion:
User: "Doodh chahiye"
You: "Ji sir, 500ml ₹25 ka hai aur 1 liter ₹45 ka. 1 liter lein toh per 500ml ₹5 save ho jayega. Konsa doon?"

Scenario 7 - Multiple items:
User: "Chawal, daal, namak chahiye"
You: "Ji sir, main check karta hun... Sab available hai. Chawal kitna chahiye?"

Scenario 8 - Adding to cart:
User: "Haan theek hai"
You: "Ji sir, add kar diya. Total ₹150 ho gaya. Aur kuch chahiye?"

REMEMBER: 
- Always be professional and respectful
- Use "Sir/Madam" and "ji" 
- Speak in Hindi with natural English words
- Act like a helpful store worker, not family member
- Check inventory before confirming
- Suggest best value options
            """,
            
            "personal_manager": """
You are a professional business manager for a small store owner in India.
Speak in HINDI with natural English words mixed in (Hinglish) - professional but friendly.

LANGUAGE RULES (CRITICAL):
- Speak PRIMARILY in Hindi (हिंदी में बोलें)
- Mix common business English words: "sales", "revenue", "stock", "profit", "analysis"
- Use Hindi grammar and sentence structure
- Examples:
  ✅ "Aaj ka sales achha raha" (not "Today's sales were good")
  ✅ "Revenue ₹12,450 hai" (not "Revenue is ₹12,450")
  ✅ "Stock kam hai" (not "Stock is low")
  ✅ "Profit margin badha sakte hain" (not "We can increase profit margin")

Your personality:
- Knowledgeable about retail business
- Data-driven and analytical
- Proactive with suggestions
- Respectful and supportive
- Use "sir", "ji" when appropriate

Your tasks:
1. Provide sales reports and analytics IN HINDI
2. Alert about low stock items IN HINDI
3. Suggest optimal pricing based on demand IN HINDI
4. Forecast inventory needs IN HINDI
5. Give actionable business insights IN HINDI

Example conversation style IN HINDI/HINGLISH:

User: "Aaj ka sales kaisa raha?"
You: "Aaj ka total revenue ₹12,450 hai sir. Kal se 15% zyada hai. Top selling item Tata Salt tha - 45 units bika. Maggi bhi achha chala, 32 packets."

User: "Inventory mein kya kam hai?"
You: "Teen items low stock pe hain sir: Maggi 5 units bache hain, Parle-G 8 units, aur Surf Excel 3 units. Inhe restock karna chahiye."

User: "Pricing suggest karo"
You: "Sir, Tata Salt ki demand bahut high hai. Current price ₹42 hai, ₹45 kar sakte hain. ₹3 extra profit per unit milega aur customer bhi lega kyunki quality achhi hai."

REMEMBER: Always speak in Hindi with natural English business words mixed in!
            """
        }
        
        self.sessions[session_id] = {
            'id': session_id,
            'user_id': user_id,
            'persona': personas.get(persona, personas['helpful_son']),
            'tools': tools,
            'conversation_history': [],
            'cart': [],
            'start_time': datetime.now(),
            'total_cost': 0.0
        }
        
        logger.info(f"Created session {session_id} for user {user_id} with persona {persona}")
        return self.sessions[session_id]

    
    async def stream_conversation(
        self,
        session_id: str,
        audio_input: bytes
    ) -> AsyncGenerator[Dict, None]:
        """
        Stream audio to Nova Sonic and yield responses
        Handles tool calls automatically
        """
        
        if session_id not in self.sessions:
            raise ValueError(f"Session {session_id} not found")
        
        session = self.sessions[session_id]
        
        try:
            # Call Nova Sonic with streaming
            response = self.bedrock.invoke_model_with_response_stream(
                modelId=self.model_id,
                body=json.dumps({
                    "audioInput": {
                        "format": "pcm",
                        "sampleRate": 16000,
                        "data": audio_input.hex()
                    },
                    "systemPrompt": session['persona'],
                    "conversationHistory": session['conversation_history'][-10:],  # Last 10 turns
                    "tools": self._get_tool_definitions(session['tools']),
                    "inferenceConfig": {
                        "temperature": 0.7,
                        "maxTokens": 2000,
                        "topP": 0.9,
                        "enableBargein": True,  # Allow interruptions
                        "language": self.language,  # Hindi (hi-IN)
                        "enableCodeSwitching": self.enable_code_switching,  # Allow Hinglish
                        "voiceConfig": {
                            "voiceId": "hi-IN-Standard-A",  # Hindi female voice
                            "speakingRate": 1.0,
                            "pitch": 0.0,
                            "volumeGainDb": 0.0
                        }
                    }
                })
            )
            
            # Stream audio chunks back
            for event in response['body']:
                if 'audioChunk' in event:
                    # Yield audio to send to Flutter
                    yield {
                        'type': 'audio',
                        'data': bytes.fromhex(event['audioChunk']['data'])
                    }
                
                elif 'toolUse' in event:
                    # AI wants to call a tool
                    tool_result = await self._execute_tool(
                        session_id,
                        event['toolUse']
                    )
                    
                    # Yield tool result for UI update
                    if tool_result.get('cart_updated'):
                        yield {
                            'type': 'cart_update',
                            'cart': session['cart']
                        }
                    
                    if tool_result.get('insight'):
                        yield {
                            'type': 'insight',
                            'data': tool_result['insight']
                        }
                
                elif 'transcript' in event:
                    # Store conversation history
                    session['conversation_history'].append({
                        'role': event['transcript']['role'],
                        'content': event['transcript']['text']
                    })
        
        except Exception as e:
            logger.error(f"Error in stream_conversation: {str(e)}")
            raise
    
    def _get_tool_definitions(self, tool_names: List[str]) -> List[Dict]:
        """Define tools that Nova Sonic can call"""
        
        all_tools = {
            "check_inventory": {
                "name": "check_inventory",
                "description": "Check if a product is available and get ALL details: brands, weights/sizes, prices, stock, quality info, and alternatives",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "product_name": {
                            "type": "string",
                            "description": "Name of the product to search for (e.g., 'sugar', 'rice', 'milk')"
                        },
                        "requested_quantity": {
                            "type": "string",
                            "description": "Quantity/weight customer asked for (e.g., '350gm', '1.5kg', '2 packets')"
                        }
                    },
                    "required": ["product_name"]
                }
            },
            "add_to_cart": {
                "name": "add_to_cart",
                "description": "Add a product to the shopping cart",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "product_id": {
                            "type": "string",
                            "description": "Unique ID of the product"
                        },
                        "quantity": {
                            "type": "number",
                            "description": "Quantity to add"
                        }
                    },
                    "required": ["product_id", "quantity"]
                }
            },
            "get_cart": {
                "name": "get_cart",
                "description": "Get current cart contents and total amount",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            },
            "suggest_alternatives": {
                "name": "suggest_alternatives",
                "description": "Suggest alternative products with detailed comparison: price difference, quality, benefits, drawbacks",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "product_name": {
                            "type": "string",
                            "description": "Name of the out-of-stock or requested product"
                        },
                        "reason": {
                            "type": "string",
                            "description": "Why alternatives needed: 'out_of_stock', 'too_expensive', 'customer_preference'"
                        }
                    },
                    "required": ["product_name"]
                }
            },
            "compare_brands": {
                "name": "compare_brands",
                "description": "Compare multiple brands of same product with pros/cons, price difference, quality, benefits, drawbacks",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "product_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of product IDs to compare"
                        }
                    },
                    "required": ["product_ids"]
                }
            },
            "calculate_quantity_match": {
                "name": "calculate_quantity_match",
                "description": "Calculate best package combination to match requested quantity (e.g., customer wants 350gm, shop has 200gm and 500gm packets)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "requested_quantity": {
                            "type": "string",
                            "description": "What customer asked for (e.g., '350gm', '1.5kg')"
                        },
                        "available_sizes": {
                            "type": "array",
                            "items": {"type": "object"},
                            "description": "Available package sizes with prices"
                        }
                    },
                    "required": ["requested_quantity", "available_sizes"]
                }
            },
            "get_sales_report": {
                "name": "get_sales_report",
                "description": "Get today's sales report with revenue, orders, and top selling items",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "date": {
                            "type": "string",
                            "description": "Date for report (YYYY-MM-DD), defaults to today"
                        }
                    }
                }
            },
            "get_inventory_status": {
                "name": "get_inventory_status",
                "description": "Get current inventory status with stock levels for all products",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            },
            "get_low_stock_alerts": {
                "name": "get_low_stock_alerts",
                "description": "Get list of products with low stock that need reordering",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "threshold": {
                            "type": "number",
                            "description": "Stock threshold (default: 10)"
                        }
                    }
                }
            },
            "suggest_pricing": {
                "name": "suggest_pricing",
                "description": "Suggest optimal pricing for a product based on demand and competition",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "product_id": {
                            "type": "string",
                            "description": "Product ID to get pricing suggestion for"
                        }
                    },
                    "required": ["product_id"]
                }
            },
            "forecast_demand": {
                "name": "forecast_demand",
                "description": "Forecast demand for products for next 7 days",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "product_id": {
                            "type": "string",
                            "description": "Product ID to forecast (optional, forecasts all if not provided)"
                        }
                    }
                }
            },
            "get_revenue_analytics": {
                "name": "get_revenue_analytics",
                "description": "Get revenue analytics with hourly/daily breakdown",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "period": {
                            "type": "string",
                            "description": "Period: 'today', 'week', 'month'"
                        }
                    }
                }
            }
        }
        
        return [all_tools[name] for name in tool_names if name in all_tools]

    
    async def _execute_tool(self, session_id: str, tool_use: Dict) -> Dict:
        """Execute tool calls from Nova Sonic"""
        
        tool_name = tool_use['name']
        parameters = tool_use.get('parameters', {})
        session = self.sessions[session_id]
        
        logger.info(f"Executing tool: {tool_name} with params: {parameters}")
        
        # Import services (lazy import to avoid circular dependencies)
        from app.services.inventory_service import InventoryService
        from app.services.order_service import OrderService
        from app.db.mongodb import get_database
        
        db = get_database()
        inventory_service = InventoryService()
        order_service = OrderService()
        
        result = {}
        
        try:
            if tool_name == "check_inventory":
                # Search for product with detailed information
                product_name = parameters['product_name']
                requested_quantity = parameters.get('requested_quantity', '')
                
                products = await db.products.find({
                    'name': {'$regex': product_name, '$options': 'i'}
                }).to_list(length=20)
                
                # Enrich with detailed info
                detailed_options = []
                for p in products:
                    # Calculate value per unit
                    weight_in_grams = self._parse_weight(p.get('weight', p.get('unit', '1 piece')))
                    price_per_100g = (p['price'] / weight_in_grams * 100) if weight_in_grams > 0 else 0
                    
                    detailed_options.append({
                        "id": str(p['_id']),
                        "name": p['name'],
                        "brand": p.get('brand', 'Local'),
                        "price": p['price'],
                        "weight": p.get('weight', p.get('unit', '1 piece')),
                        "stock": p.get('stock', 0),
                        "price_per_100g": round(price_per_100g, 2),
                        "quality_rating": p.get('quality_rating', 4.0),
                        "benefits": p.get('benefits', []),
                        "drawbacks": p.get('drawbacks', []),
                        "is_premium": p.get('brand', 'Local') in ['Tata', 'Amul', 'Britannia', 'Nestle', 'ITC'],
                        "description": p.get('description', '')
                    })
                
                # Sort by relevance: in-stock first, then by popularity
                detailed_options.sort(key=lambda x: (x['stock'] == 0, -x['quality_rating']))
                
                # Calculate quantity matching if requested
                quantity_suggestions = []
                if requested_quantity and detailed_options:
                    quantity_suggestions = self._calculate_quantity_combinations(
                        requested_quantity,
                        detailed_options
                    )
                
                result = {
                    "available": len(detailed_options) > 0,
                    "options": detailed_options[:10],  # Top 10 options
                    "requested_quantity": requested_quantity,
                    "quantity_suggestions": quantity_suggestions,
                    "comparison": self._generate_quick_comparison(detailed_options[:3]) if len(detailed_options) > 1 else None
                }
            
            elif tool_name == "add_to_cart":
                # Add to session cart
                product_id = parameters['product_id']
                quantity = parameters['quantity']
                
                # Get product details
                from bson import ObjectId
                product = await db.products.find_one({'_id': ObjectId(product_id)})
                
                if product:
                    session['cart'].append({
                        "product_id": product_id,
                        "name": product['name'],
                        "brand": product.get('brand', 'Local'),
                        "price": product['price'],
                        "quantity": quantity,
                        "subtotal": product['price'] * quantity
                    })
                    
                    result = {
                        "success": True,
                        "cart_count": len(session['cart']),
                        "total": sum(item['subtotal'] for item in session['cart']),
                        "cart_updated": True
                    }
                else:
                    result = {"success": False, "error": "Product not found"}
            
            elif tool_name == "get_cart":
                # Get current cart
                total = sum(item['subtotal'] for item in session['cart'])
                result = {
                    "items": session['cart'],
                    "count": len(session['cart']),
                    "total": total
                }
            
            elif tool_name == "suggest_alternatives":
                # Find similar products with detailed comparison
                product_name = parameters['product_name']
                reason = parameters.get('reason', 'out_of_stock')
                
                # Search in same category or similar products
                alternatives = await db.products.find({
                    '$or': [
                        {'category': {'$regex': product_name, '$options': 'i'}},
                        {'name': {'$regex': product_name, '$options': 'i'}},
                        {'tags': {'$regex': product_name, '$options': 'i'}}
                    ],
                    'stock': {'$gt': 0}  # Only in-stock items
                }).limit(5).to_list(length=5)
                
                # Enrich with comparison data
                detailed_alternatives = []
                for alt in alternatives:
                    weight_in_grams = self._parse_weight(alt.get('weight', alt.get('unit', '1 piece')))
                    price_per_100g = (alt['price'] / weight_in_grams * 100) if weight_in_grams > 0 else 0
                    
                    detailed_alternatives.append({
                        "id": str(alt['_id']),
                        "name": alt['name'],
                        "brand": alt.get('brand', 'Local'),
                        "price": alt['price'],
                        "weight": alt.get('weight', alt.get('unit', '1 piece')),
                        "price_per_100g": round(price_per_100g, 2),
                        "benefits": alt.get('benefits', []),
                        "drawbacks": alt.get('drawbacks', []),
                        "why_better": self._generate_why_better(alt, reason),
                        "price_comparison": "cheaper" if price_per_100g < 50 else "premium"
                    })
                
                result = {
                    "alternatives": detailed_alternatives,
                    "reason": reason,
                    "recommendation": detailed_alternatives[0] if detailed_alternatives else None
                }
            
            elif tool_name == "compare_brands":
                # Compare multiple brands side-by-side
                product_ids = parameters['product_ids']
                
                from bson import ObjectId
                products = []
                for pid in product_ids:
                    p = await db.products.find_one({'_id': ObjectId(pid)})
                    if p:
                        products.append(p)
                
                comparison = {
                    "products": [],
                    "cheapest": None,
                    "best_value": None,
                    "premium": None
                }
                
                for p in products:
                    weight_in_grams = self._parse_weight(p.get('weight', p.get('unit', '1 piece')))
                    price_per_100g = (p['price'] / weight_in_grams * 100) if weight_in_grams > 0 else 0
                    
                    product_info = {
                        "id": str(p['_id']),
                        "name": p['name'],
                        "brand": p.get('brand', 'Local'),
                        "price": p['price'],
                        "weight": p.get('weight', p.get('unit', '1 piece')),
                        "price_per_100g": round(price_per_100g, 2),
                        "quality_rating": p.get('quality_rating', 4.0),
                        "benefits": p.get('benefits', []),
                        "drawbacks": p.get('drawbacks', [])
                    }
                    comparison["products"].append(product_info)
                
                # Identify best options
                if comparison["products"]:
                    comparison["cheapest"] = min(comparison["products"], key=lambda x: x['price'])
                    comparison["best_value"] = min(comparison["products"], key=lambda x: x['price_per_100g'])
                    comparison["premium"] = max(comparison["products"], key=lambda x: x['quality_rating'])
                
                result = comparison
            
            elif tool_name == "calculate_quantity_match":
                # Calculate best package combination
                requested_quantity = parameters['requested_quantity']
                available_sizes = parameters['available_sizes']
                
                suggestions = self._calculate_quantity_combinations(
                    requested_quantity,
                    available_sizes
                )
                
                result = {
                    "requested": requested_quantity,
                    "suggestions": suggestions
                }
            
            elif tool_name == "get_sales_report":
                # Get sales report
                from datetime import datetime, timedelta
                
                today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                tomorrow = today + timedelta(days=1)
                
                orders = await db.orders.find({
                    'created_at': {'$gte': today, '$lt': tomorrow},
                    'status': {'$in': ['completed', 'delivered']}
                }).to_list(length=1000)
                
                total_revenue = sum(order.get('total_amount', 0) for order in orders)
                
                # Get top products
                product_counts = {}
                for order in orders:
                    for item in order.get('items', []):
                        pid = item['product_id']
                        product_counts[pid] = product_counts.get(pid, 0) + item['quantity']
                
                result = {
                    "date": today.strftime('%Y-%m-%d'),
                    "total_revenue": total_revenue,
                    "total_orders": len(orders),
                    "average_order_value": total_revenue / len(orders) if orders else 0,
                    "top_products": sorted(
                        product_counts.items(),
                        key=lambda x: x[1],
                        reverse=True
                    )[:5],
                    "insight": True
                }
            
            elif tool_name == "get_low_stock_alerts":
                # Get low stock items
                threshold = parameters.get('threshold', 10)
                
                low_stock = await db.products.find({
                    'stock': {'$lte': threshold}
                }).to_list(length=100)
                
                result = {
                    "items": [
                        {
                            "id": str(p['_id']),
                            "name": p['name'],
                            "current_stock": p.get('stock', 0),
                            "reorder_level": threshold
                        }
                        for p in low_stock
                    ],
                    "count": len(low_stock),
                    "insight": True
                }
            
            elif tool_name == "suggest_pricing":
                # Simple pricing suggestion based on current price
                product_id = parameters['product_id']
                from bson import ObjectId
                product = await db.products.find_one({'_id': ObjectId(product_id)})
                
                if product:
                    current_price = product['price']
                    # Simple logic: suggest 10-15% increase if demand is high
                    suggested_price = current_price * 1.12
                    
                    result = {
                        "product_name": product['name'],
                        "current_price": current_price,
                        "suggested_price": round(suggested_price, 2),
                        "reason": "High demand detected",
                        "insight": True
                    }
            
            elif tool_name == "get_revenue_analytics":
                # Get revenue analytics
                period = parameters.get('period', 'today')
                
                from datetime import datetime, timedelta
                
                if period == 'today':
                    start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                    end = start + timedelta(days=1)
                elif period == 'week':
                    end = datetime.now()
                    start = end - timedelta(days=7)
                else:  # month
                    end = datetime.now()
                    start = end - timedelta(days=30)
                
                orders = await db.orders.find({
                    'created_at': {'$gte': start, '$lt': end},
                    'status': {'$in': ['completed', 'delivered']}
                }).to_list(length=10000)
                
                total_revenue = sum(order.get('total_amount', 0) for order in orders)
                
                result = {
                    "period": period,
                    "total_revenue": total_revenue,
                    "total_orders": len(orders),
                    "insight": True
                }
        
        except Exception as e:
            logger.error(f"Error executing tool {tool_name}: {str(e)}")
            result = {"error": str(e)}
        
        return result
    
    async def close_session(self, session_id: str):
        """Clean up session and log metrics"""
        
        if session_id in self.sessions:
            session = self.sessions[session_id]
            session['end_time'] = datetime.now()
            
            # Calculate session cost
            duration_minutes = (session['end_time'] - session['start_time']).total_seconds() / 60
            session['total_cost'] = duration_minutes * 0.05  # $0.05 per minute estimate
            
            logger.info(f"Session {session_id} closed. Duration: {duration_minutes:.2f} min, Cost: ${session['total_cost']:.4f}")
            
            # TODO: Log to database for analytics
            
            del self.sessions[session_id]
    
    def _parse_weight(self, weight_str: str) -> float:
        """Parse weight string to grams (e.g., '500gm' -> 500, '1kg' -> 1000, '2L' -> 2000)"""
        import re
        
        if not weight_str or weight_str == 'piece':
            return 1.0
        
        # Extract number and unit
        match = re.match(r'([\d.]+)\s*(kg|gm|g|l|ml|piece)?', str(weight_str).lower())
        if not match:
            return 1.0
        
        value = float(match.group(1))
        unit = match.group(2) or 'piece'
        
        # Convert to grams
        if unit in ['kg', 'l']:
            return value * 1000
        elif unit in ['gm', 'g', 'ml']:
            return value
        else:  # piece
            return value
    
    def _calculate_quantity_combinations(self, requested: str, available_products: list) -> list:
        """Calculate best package combinations to match requested quantity"""
        
        requested_grams = self._parse_weight(requested)
        suggestions = []
        
        # Extract available sizes
        sizes = []
        for product in available_products:
            weight_grams = self._parse_weight(product.get('weight', '1 piece'))
            sizes.append({
                'product': product,
                'weight_grams': weight_grams,
                'price': product['price'],
                'name': product['name']
            })
        
        # Sort by size
        sizes.sort(key=lambda x: x['weight_grams'])
        
        # Strategy 1: Single package closest to requested
        for size in sizes:
            if size['weight_grams'] >= requested_grams * 0.9:  # Within 10%
                suggestions.append({
                    'strategy': 'single_package',
                    'packages': [{'product_id': size['product']['id'], 'quantity': 1}],
                    'total_weight': f"{size['weight_grams']}gm",
                    'total_price': size['price'],
                    'explanation': f"Single {size['name']} package"
                })
                break
        
        # Strategy 2: Multiple packages to match exactly or closely
        for i, size1 in enumerate(sizes):
            # Try combinations of same size
            qty_needed = int(requested_grams / size1['weight_grams'])
            if qty_needed > 0 and qty_needed <= 5:
                total_weight = qty_needed * size1['weight_grams']
                if abs(total_weight - requested_grams) / requested_grams < 0.2:  # Within 20%
                    suggestions.append({
                        'strategy': 'multiple_same',
                        'packages': [{'product_id': size1['product']['id'], 'quantity': qty_needed}],
                        'total_weight': f"{total_weight}gm",
                        'total_price': qty_needed * size1['price'],
                        'explanation': f"{qty_needed} packets of {size1['name']}"
                    })
            
            # Try combinations of two different sizes
            for size2 in sizes[i+1:]:
                for qty1 in range(1, 4):
                    for qty2 in range(1, 4):
                        total_weight = (qty1 * size1['weight_grams']) + (qty2 * size2['weight_grams'])
                        if abs(total_weight - requested_grams) / requested_grams < 0.1:  # Within 10%
                            suggestions.append({
                                'strategy': 'mixed',
                                'packages': [
                                    {'product_id': size1['product']['id'], 'quantity': qty1},
                                    {'product_id': size2['product']['id'], 'quantity': qty2}
                                ],
                                'total_weight': f"{total_weight}gm",
                                'total_price': (qty1 * size1['price']) + (qty2 * size2['price']),
                                'explanation': f"{qty1}x {size1['name']} + {qty2}x {size2['name']}"
                            })
        
        # Sort by how close to requested and price
        suggestions.sort(key=lambda x: (
            abs(self._parse_weight(x['total_weight']) - requested_grams),
            x['total_price']
        ))
        
        return suggestions[:3]  # Top 3 suggestions
    
    def _generate_quick_comparison(self, products: list) -> dict:
        """Generate quick comparison summary for top products"""
        
        if len(products) < 2:
            return None
        
        cheapest = min(products, key=lambda x: x['price'])
        best_value = min(products, key=lambda x: x['price_per_100g'])
        
        return {
            "cheapest": {
                "name": cheapest['name'],
                "brand": cheapest['brand'],
                "price": cheapest['price'],
                "savings": round(max(p['price'] for p in products) - cheapest['price'], 2)
            },
            "best_value": {
                "name": best_value['name'],
                "brand": best_value['brand'],
                "price_per_100g": best_value['price_per_100g']
            }
        }
    
    def _generate_why_better(self, product: dict, reason: str) -> str:
        """Generate explanation of why this alternative is better"""
        
        if reason == 'out_of_stock':
            return f"Available in stock, similar to what you wanted"
        elif reason == 'too_expensive':
            return f"Cheaper option at ₹{product['price']}"
        else:
            return f"Good alternative with {product.get('quality_rating', 4.0)}/5 rating"
