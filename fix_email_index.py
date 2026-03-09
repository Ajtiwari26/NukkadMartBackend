"""
Fix MongoDB email index to allow multiple null values
"""
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv

load_dotenv()

async def fix_email_index():
    """Drop the unique email index and create a sparse unique index"""
    
    # Connect to MongoDB
    mongodb_url = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
    client = AsyncIOMotorClient(mongodb_url)
    db = client["nukkadmart"]
    
    print("Connected to MongoDB")
    
    # Drop the existing email_1 index
    try:
        await db.users.drop_index("email_1")
        print("✓ Dropped existing email_1 index")
    except Exception as e:
        print(f"Note: Could not drop email_1 index (may not exist): {e}")
    
    # Create a sparse unique index on email
    # Sparse index only includes documents that have the email field
    # This allows multiple documents with missing email field
    try:
        await db.users.create_index(
            "email",
            unique=True,
            sparse=True,  # Key difference - allows multiple null/missing values
            name="email_sparse_unique"
        )
        print("✓ Created sparse unique index on email")
    except Exception as e:
        print(f"Note: Could not create sparse index: {e}")
    
    # List all indexes
    indexes = await db.users.list_indexes().to_list(length=None)
    print("\nCurrent indexes on users collection:")
    for idx in indexes:
        print(f"  - {idx['name']}: {idx.get('key', {})}")
        if idx.get('unique'):
            print(f"    (unique, sparse={idx.get('sparse', False)})")
    
    client.close()
    print("\n✓ Done!")

if __name__ == "__main__":
    asyncio.run(fix_email_index())
