"""
Test Nova 2 Sonic with Hindi text to see if it supports Hindi
"""
import boto3
import json
import os
from dotenv import load_dotenv

load_dotenv()

bedrock = boto3.client(
    'bedrock-runtime',
    region_name='us-east-1',
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
)

# Test with Hindi text
hindi_prompt = "Namaste, aapko kya chahiye? Main aapki help kar sakta hun."

try:
    print("Testing Nova 2 Sonic with Hindi text...")
    print(f"Input: {hindi_prompt}\n")
    
    response = bedrock.invoke_model(
        modelId='amazon.nova-2-sonic-v1:0',
        body=json.dumps({
            "inputText": hindi_prompt,
            "inferenceConfig": {
                "temperature": 0.7,
                "maxTokens": 100
            }
        })
    )
    
    response_body = json.loads(response['body'].read())
    print("✓ Nova 2 Sonic Response:")
    print(json.dumps(response_body, indent=2))
    
except Exception as e:
    print(f"❌ Error: {str(e)}")
    print("\nNova Sonic might not support text-only input.")
    print("It requires audio input for speech-to-speech.")
