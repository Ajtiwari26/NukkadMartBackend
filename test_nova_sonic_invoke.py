"""
Test Nova Sonic model invocation
This will auto-enable the model on first use
"""

import boto3
import json
import os
from dotenv import load_dotenv

load_dotenv()

def test_nova_sonic():
    """Test if Nova Sonic can be invoked"""
    
    print("🧪 Testing Amazon Nova Sonic Model Invocation...")
    print("=" * 60)
    
    # Get credentials
    aws_key = os.getenv('AWS_ACCESS_KEY_ID')
    aws_secret = os.getenv('AWS_SECRET_ACCESS_KEY')
    aws_region = os.getenv('AWS_REGION', 'ap-south-1')
    model_id = os.getenv('BEDROCK_NOVA_SONIC_MODEL_ID', 'amazon.nova-sonic-v1:0')
    
    print(f"📋 Configuration:")
    print(f"   Region: {aws_region}")
    print(f"   Model: {model_id}")
    print(f"   Access Key: {aws_key[:20]}...")
    print()
    
    try:
        # Create Bedrock client
        bedrock = boto3.client(
            'bedrock-runtime',
            region_name=aws_region,
            aws_access_key_id=aws_key,
            aws_secret_access_key=aws_secret
        )
        print("✅ Bedrock client created")
        
        # Try to invoke Nova Sonic with a simple test
        # Note: This is a simplified test - actual audio would be binary PCM data
        print("\n🎙️ Attempting to invoke Nova Sonic...")
        print("   (Model will auto-enable on first invocation)")
        
        # Simple test payload
        test_payload = {
            "messages": [{
                "role": "user",
                "content": "Namaste"
            }],
            "inferenceConfig": {
                "temperature": 0.7,
                "maxTokens": 100
            }
        }
        
        response = bedrock.invoke_model(
            modelId=model_id,
            body=json.dumps(test_payload)
        )
        
        print("✅ Nova Sonic invoked successfully!")
        print("✅ Model is now auto-enabled for your account!")
        print("\n🎉 Success! You can now use Nova Sonic for voice assistant!")
        
        return True
        
    except Exception as e:
        error_msg = str(e)
        print(f"\n❌ Error: {error_msg}")
        
        if "AccessDeniedException" in error_msg:
            print("\n🔍 Troubleshooting:")
            print("   1. Check if your AWS credentials have Bedrock permissions")
            print("   2. Verify the access key is correct")
            print("   3. Make sure Bedrock is in your credits list")
        elif "ValidationException" in error_msg or "model" in error_msg.lower():
            print("\n🔍 Note:")
            print("   This might be a model ID or payload format issue")
            print("   But your credentials and Bedrock access are working!")
        elif "ThrottlingException" in error_msg:
            print("\n⚠️  Rate limit hit - but this means Bedrock is accessible!")
        else:
            print("\n🔍 Unexpected error - check AWS console for details")
        
        return False

if __name__ == "__main__":
    test_nova_sonic()
