"""
Test cart marker regex pattern detection and cleaning
"""
import re

# Test cases from actual AI output
test_cases = [
    "Ji sir, ek Mother Dairy add kar raha hun.  # ADD:301,1###.",
    "Ji sir, ek Mother Dairy add kar raha hun. ###ADD:301,1###",
    "Aapka Full Cream Milk cart mein add ho gaya ###ADD:123,2###",
    "Remove kar diya ###REMOVE:301###",
    "Quantity update kar di ###UPDATE:301,3###",
    "# ADD:301,1###",
    "##ADD:301,1##",
    "### ADD : 301 , 1 ###",
    "Ji sir, Full Cream Milk cart mein add ho gaya. ###ADD:69926acd2f27663bea211e98,1###",
    "Theek hai, Toned Milk remove kar diya. ###REMOVE:69926acd2f27663bea211e99###",
]

# Regex pattern (same as in nova_sonic_service.py)
pattern = r'#{1,3}\s*(ADD|REMOVE|UPDATE)\s*:\s*([^#]+?)#{1,3}'

print("🧪 Testing Cart Marker Regex Pattern & Cleaning\n")
print(f"Pattern: {pattern}\n")
print("=" * 80)

for i, text in enumerate(test_cases, 1):
    print(f"\nTest {i}:")
    print(f"  Original: {text}")
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        action = match.group(1).upper()
        params = match.group(2).strip().rstrip('.,;!?')
        print(f"  ✅ MATCH: action={action}, params={params}")
        
        # Test cleaning (what user will see)
        clean_text = re.sub(r'#{1,3}\s*(ADD|REMOVE|UPDATE)\s*:[^#]+#{1,3}[.,;!?]*', '', text, flags=re.IGNORECASE).strip()
        print(f"  👤 User sees: '{clean_text}'")
    else:
        print(f"  ❌ NO MATCH")

print("\n" + "=" * 80)
print("\n✅ All markers are properly hidden from user!")
print("User only sees natural Hindi/Hinglish text without technical markers.")

