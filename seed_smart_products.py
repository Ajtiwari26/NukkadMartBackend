"""
Seed database with smart products that have detailed information
for the enhanced voice assistant
"""

import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv

load_dotenv()

# Sample products with detailed information
SMART_PRODUCTS = [
    # Rice varieties
    {
        "name": "Basmati Rice",
        "brand": "India Gate",
        "price": 180,
        "weight": "1kg",
        "stock": 50,
        "category": "Groceries",
        "quality_rating": 4.5,
        "benefits": [
            "Long grain premium rice",
            "Aromatic fragrance",
            "Cooks fluffy"
        ],
        "drawbacks": ["Expensive"],
        "description": "Premium basmati rice for special occasions",
        "tags": ["rice", "chawal", "basmati"],
        "unit": "1kg"
    },
    {
        "name": "Regular Rice",
        "brand": "Local",
        "price": 40,
        "weight": "1kg",
        "stock": 100,
        "category": "Groceries",
        "quality_rating": 3.5,
        "benefits": ["Affordable", "Good for daily use"],
        "drawbacks": ["Not aromatic", "Shorter grain"],
        "description": "Regular rice for everyday cooking",
        "tags": ["rice", "chawal", "regular"],
        "unit": "1kg"
    },
    {
        "name": "Basmati Rice",
        "brand": "India Gate",
        "price": 95,
        "weight": "500gm",
        "stock": 30,
        "category": "Groceries",
        "quality_rating": 4.5,
        "benefits": ["Premium quality", "Smaller pack"],
        "drawbacks": ["Higher price per kg"],
        "description": "Premium basmati rice 500gm pack",
        "tags": ["rice", "chawal", "basmati"],
        "unit": "500gm"
    },
    
    # Salt varieties
    {
        "name": "Tata Salt",
        "brand": "Tata",
        "price": 42,
        "weight": "1kg",
        "stock": 80,
        "category": "Groceries",
        "quality_rating": 4.8,
        "benefits": [
            "Iodized for health",
            "Free flowing",
            "No impurities",
            "Trusted brand"
        ],
        "drawbacks": ["Slightly expensive"],
        "description": "Premium iodized salt",
        "tags": ["salt", "namak", "iodized"],
        "unit": "1kg"
    },
    {
        "name": "Annapurna Salt",
        "brand": "Annapurna",
        "price": 35,
        "weight": "1kg",
        "stock": 60,
        "category": "Groceries",
        "quality_rating": 4.2,
        "benefits": ["Iodized", "Good quality", "Affordable"],
        "drawbacks": ["Less known brand"],
        "description": "Iodized salt at affordable price",
        "tags": ["salt", "namak", "iodized"],
        "unit": "1kg"
    },
    {
        "name": "Local Salt",
        "brand": "Local",
        "price": 28,
        "weight": "1kg",
        "stock": 100,
        "category": "Groceries",
        "quality_rating": 3.5,
        "benefits": ["Cheapest option", "Basic quality"],
        "drawbacks": ["Not iodized", "May have impurities"],
        "description": "Basic salt for budget shopping",
        "tags": ["salt", "namak"],
        "unit": "1kg"
    },
    
    # Noodles
    {
        "name": "Maggi Masala",
        "brand": "Nestle",
        "price": 12,
        "weight": "70gm",
        "stock": 0,  # Out of stock
        "category": "Instant Food",
        "quality_rating": 4.7,
        "benefits": ["Popular taste", "Quick to cook", "Kids favorite"],
        "drawbacks": ["Contains MSG"],
        "description": "Classic Maggi noodles",
        "tags": ["noodles", "maggi", "instant"],
        "unit": "70gm"
    },
    {
        "name": "Top Ramen",
        "brand": "Top Ramen",
        "price": 12,
        "weight": "70gm",
        "stock": 50,
        "category": "Instant Food",
        "quality_rating": 4.3,
        "benefits": ["Similar to Maggi", "Good taste", "Slightly spicy"],
        "drawbacks": ["Less popular than Maggi"],
        "description": "Tasty instant noodles",
        "tags": ["noodles", "instant"],
        "unit": "70gm"
    },
    {
        "name": "Yippee Noodles",
        "brand": "Sunfeast",
        "price": 10,
        "weight": "60gm",
        "stock": 60,
        "category": "Instant Food",
        "quality_rating": 4.0,
        "benefits": ["Cheaper", "More masala", "Kids like it"],
        "drawbacks": ["Smaller pack", "Very spicy"],
        "description": "Budget-friendly instant noodles",
        "tags": ["noodles", "instant", "yippee"],
        "unit": "60gm"
    },
    
    # Flour/Atta
    {
        "name": "Aashirvaad Atta",
        "brand": "Aashirvaad",
        "price": 40,
        "weight": "1kg",
        "stock": 70,
        "category": "Groceries",
        "quality_rating": 4.6,
        "benefits": ["Soft rotis", "Good quality wheat", "Trusted brand"],
        "drawbacks": ["Slightly expensive"],
        "description": "Premium wheat flour",
        "tags": ["atta", "flour", "wheat"],
        "unit": "1kg"
    },
    {
        "name": "Aashirvaad Atta",
        "brand": "Aashirvaad",
        "price": 22,
        "weight": "500gm",
        "stock": 40,
        "category": "Groceries",
        "quality_rating": 4.6,
        "benefits": ["Same quality", "Smaller pack"],
        "drawbacks": ["Higher price per kg"],
        "description": "Premium wheat flour 500gm",
        "tags": ["atta", "flour", "wheat"],
        "unit": "500gm"
    },
    {
        "name": "Aashirvaad Atta",
        "brand": "Aashirvaad",
        "price": 190,
        "weight": "5kg",
        "stock": 20,
        "category": "Groceries",
        "quality_rating": 4.6,
        "benefits": ["Best value", "Bulk pack", "Lasts longer"],
        "drawbacks": ["Heavy to carry"],
        "description": "Premium wheat flour 5kg bulk pack",
        "tags": ["atta", "flour", "wheat"],
        "unit": "5kg"
    },
    
    # Milk
    {
        "name": "Amul Taza Milk",
        "brand": "Amul",
        "price": 25,
        "weight": "500ml",
        "stock": 30,
        "category": "Dairy",
        "quality_rating": 4.7,
        "benefits": ["Fresh", "Trusted brand", "Homogenized"],
        "drawbacks": ["Small pack"],
        "description": "Fresh toned milk",
        "tags": ["milk", "doodh", "dairy"],
        "unit": "500ml"
    },
    {
        "name": "Amul Taza Milk",
        "brand": "Amul",
        "price": 45,
        "weight": "1L",
        "stock": 40,
        "category": "Dairy",
        "quality_rating": 4.7,
        "benefits": ["Better value", "Fresh", "Lasts 2-3 days"],
        "drawbacks": [],
        "description": "Fresh toned milk 1 liter",
        "tags": ["milk", "doodh", "dairy"],
        "unit": "1L"
    },
    
    # Detergent
    {
        "name": "Surf Excel",
        "brand": "Surf Excel",
        "price": 180,
        "weight": "1kg",
        "stock": 25,
        "category": "Household",
        "quality_rating": 4.8,
        "benefits": [
            "Removes tough stains",
            "Gentle on clothes",
            "Pleasant smell",
            "Gentle on hands"
        ],
        "drawbacks": ["Expensive"],
        "description": "Premium detergent powder",
        "tags": ["detergent", "washing powder", "surf"],
        "unit": "1kg"
    },
    {
        "name": "Rin Detergent",
        "brand": "Rin",
        "price": 120,
        "weight": "1kg",
        "stock": 35,
        "category": "Household",
        "quality_rating": 4.2,
        "benefits": ["Good cleaning", "Affordable", "Whitens clothes"],
        "drawbacks": ["Strong smell", "Harsh on hands"],
        "description": "Mid-range detergent powder",
        "tags": ["detergent", "washing powder", "rin"],
        "unit": "1kg"
    },
    {
        "name": "Local Detergent",
        "brand": "Local",
        "price": 80,
        "weight": "1kg",
        "stock": 50,
        "category": "Household",
        "quality_rating": 3.5,
        "benefits": ["Cheapest", "Basic cleaning"],
        "drawbacks": [
            "Doesn't remove tough stains",
            "Very harsh on hands",
            "Makes clothes rough"
        ],
        "description": "Budget detergent powder",
        "tags": ["detergent", "washing powder"],
        "unit": "1kg"
    },
    
    # Tea
    {
        "name": "Tata Tea Gold",
        "brand": "Tata",
        "price": 180,
        "weight": "500gm",
        "stock": 40,
        "category": "Beverages",
        "quality_rating": 4.7,
        "benefits": ["Premium taste", "Strong aroma", "Long lasting"],
        "drawbacks": ["Expensive"],
        "description": "Premium tea leaves",
        "tags": ["tea", "chai", "chai patti"],
        "unit": "500gm"
    },
    
    # Sugar
    {
        "name": "Tata Sugar",
        "brand": "Tata",
        "price": 45,
        "weight": "1kg",
        "stock": 60,
        "category": "Groceries",
        "quality_rating": 4.5,
        "benefits": ["Pure", "Free flowing", "Trusted brand"],
        "drawbacks": [],
        "description": "Pure white sugar",
        "tags": ["sugar", "chini"],
        "unit": "1kg"
    },
    {
        "name": "Jaggery (Gur)",
        "brand": "Local",
        "price": 60,
        "weight": "1kg",
        "stock": 30,
        "category": "Groceries",
        "quality_rating": 4.3,
        "benefits": [
            "Natural sweetener",
            "Rich in iron",
            "Good for digestion",
            "No chemicals"
        ],
        "drawbacks": ["Slightly expensive", "Different taste"],
        "description": "Natural jaggery",
        "tags": ["jaggery", "gur", "sweetener"],
        "unit": "1kg"
    },
    
    # Dal/Lentils
    {
        "name": "Toor Dal",
        "brand": "Tata Sampann",
        "price": 120,
        "weight": "1kg",
        "stock": 45,
        "category": "Groceries",
        "quality_rating": 4.6,
        "benefits": ["Premium quality", "Clean", "Cooks well"],
        "drawbacks": ["Expensive"],
        "description": "Premium toor dal",
        "tags": ["dal", "lentils", "toor"],
        "unit": "1kg"
    },
    {
        "name": "Toor Dal",
        "brand": "Local",
        "price": 90,
        "weight": "1kg",
        "stock": 60,
        "category": "Groceries",
        "quality_rating": 3.8,
        "benefits": ["Affordable", "Good for daily use"],
        "drawbacks": ["May need more cleaning", "Less consistent quality"],
        "description": "Regular toor dal",
        "tags": ["dal", "lentils", "toor"],
        "unit": "1kg"
    }
]


async def seed_database():
    """Seed database with smart products"""
    
    # Connect to MongoDB
    mongodb_uri = os.getenv('MONGODB_URI', 'mongodb://localhost:27017')
    client = AsyncIOMotorClient(mongodb_uri)
    db = client['nukkadmart']
    
    print("🌱 Seeding database with smart products...")
    
    # Clear existing products (optional)
    # await db.products.delete_many({})
    # print("   Cleared existing products")
    
    # Insert products
    result = await db.products.insert_many(SMART_PRODUCTS)
    print(f"✅ Inserted {len(result.inserted_ids)} products")
    
    # Create indexes
    await db.products.create_index([("name", "text"), ("tags", "text")])
    await db.products.create_index("category")
    await db.products.create_index("brand")
    print("✅ Created indexes")
    
    # Print summary
    print("\n📊 Product Summary:")
    categories = {}
    for product in SMART_PRODUCTS:
        cat = product['category']
        categories[cat] = categories.get(cat, 0) + 1
    
    for cat, count in categories.items():
        print(f"   {cat}: {count} products")
    
    print(f"\n🎉 Database seeded successfully!")
    print(f"   Total products: {len(SMART_PRODUCTS)}")
    print(f"   Ready for voice assistant testing!")
    
    client.close()


if __name__ == "__main__":
    asyncio.run(seed_database())
