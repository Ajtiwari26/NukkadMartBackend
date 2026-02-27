"""
Test basic Bedrock access with the provided credentials
"""

import boto3
import os
from dotenv import load_dotenv
from botocore.exceptions import ClientError

load_dotenv()

def test_bedrock_access():
    """Test if we can access Bedrock at all"""
    
    print("🧪 Testing Amazon Bedrock Access...")
    print("=" * 60)
    
    aws_key = os.getenv('AWS_ACCESS_KEY_ID')
    aws_secret = os.getenv('AWS_SECRET_ACCESS_KEY')
    aws_region = os.getenv('AWS_REGION', 'ap-south-1')
    
    print(f"📋 Credentials:")
    print(f"   Access Key: {aws_key}")
    print(f"   Secret (first 20 chars): {aws_secret[:20]}...")
    print(f"   Region: {aws_region}")
    print()
    
    # Test 1: Try bedrock-runtime
    print("Test 1: Bedrock Runtime Client")
    try:
        bedrock_runtime = boto3.client(
            'bedrock-runtime',
            region_name=aws_region,
            aws_access_key_id=aws_key,
            aws_secret_access_key=aws_secret
        )
        print("✅ Bedrock Runtime client created")
    except Exception as e:
        print(f"❌ Error: {e}")
    
    # Test 2: Try bedrock (control plane)
    print("\nTest 2: Bedrock Control Plane Client")
    try:
        bedrock = boto3.client(
            'bedrock',
            region_name=aws_region,
            aws_access_key_id=aws_key,
            aws_secret_access_key=aws_secret
        )
        print("✅ Bedrock client created")
        
        # Try to list foundation models
        print("\nTest 3: List Foundation Models")
        try:
            response = bedrock.list_foundation_models()
            print(f"✅ Successfully listed models!")
            print(f"   Found {len(response.get('modelSummaries', []))} models")
            
            # Look for Nova models
            nova_models = [m for m in response.get('modelSummaries', []) 
                          if 'nova' in m.get('modelId', '').lower()]
            if nova_models:
                print(f"\n🎉 Found {len(nova_models)} Nova models:")
                for model in nova_models[:5]:  # Show first 5
                    print(f"   - {model.get('modelId')}")
            else:
                print("\n⚠️  No Nova models found in list")
                
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_msg = e.response['Error']['Message']
            print(f"❌ Error listing models: {error_code}")
            print(f"   Message: {error_msg}")
            
            if error_code == 'UnrecognizedClientException':
                print("\n🔍 Analysis:")
                print("   The credentials format might be incorrect")
                print("   'BedrockAPIKey-' prefix suggests this might be a special key format")
                print("   You may need to:")
                print("   1. Check AWS Console for the correct credential format")
                print("   2. Verify this is an IAM access key (not API key)")
                print("   3. Ensure the key has Bedrock permissions")
            
    except Exception as e:
        print(f"❌ Error: {e}")
    
    print("\n" + "=" * 60)
    print("💡 Recommendation:")
    print("   The 'BedrockAPIKey-' prefix is unusual for AWS credentials")
    print("   Standard AWS credentials look like: AKIA...")
    print("   Please verify your credentials in AWS Console:")
    print("   1. Go to IAM → Users → Your User → Security Credentials")
    print("   2. Create new Access Key if needed")
    print("   3. Ensure user has 'AmazonBedrockFullAccess' policy")

if __name__ == "__main__":
    test_bedrock_access()
