#!/bin/bash

echo "🔄 Restarting Backend Server..."

# Kill existing process on port 8000
echo "Stopping existing server..."
lsof -ti:8000 | xargs kill -9 2>/dev/null || echo "No process on port 8000"

# Install all dependencies from requirements.txt
echo "📦 Installing all dependencies..."
if [ -f "requirements.txt" ]; then
    pip3 install -r requirements.txt --user
else
    echo "⚠️  requirements.txt not found, installing common dependencies..."
    pip3 install fastapi uvicorn motor pydantic pydantic-settings python-multipart pillow groq --user
fi

echo ""
echo "🚀 Starting backend server..."
python3 -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
