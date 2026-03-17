"""
LLM Intent-Based Cache — Setup & Verification Script
Tests the canonical intent caching system.

Usage:
    cd /Users/ajay/Desktop/nukkadMart/NukkadBackend
    python3 scripts/setup_llm_cache.py
"""
import asyncio
import sys
import os
import json
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()


async def main():
    print("=" * 60)
    print("  NukkadMart LLM Intent-Based Cache — Setup & Verification")
    print("=" * 60)

    # 1. Test Redis Connection
    print("\n[1/5] Testing Upstash Redis connection...")
    from app.db.redis import RedisClient
    await RedisClient.connect()

    if RedisClient._http_client is None:
        print("  ❌ Redis connection failed!")
        return False

    pong = await RedisClient._execute("PING")
    if pong == "PONG":
        print("  ✅ Upstash Redis connected")
    else:
        print(f"  ❌ Unexpected PING response: {pong}")
        return False

    # 2. Test Fast Intent Extraction
    print("\n[2/5] Testing fast intent extraction (regex, <1ms)...")
    from app.core.llm_cache import fast_extract_intent, _are_opposite_intents

    test_cases = [
        ("coffee add karo", "add", "coffee"),
        ("mujhe coffee chahiye", "add", "coffee"),
        ("pizza order karo", "add", "pizza"),
        ("milk cancel karo", "remove", "milk"),
        ("doodh repeat karo", "repeat", "doodh"),
        ("rice hata do", "remove", "rice"),
        ("sugar ki quantity badhao", "update", "sugar"),
        ("paneer ka price kya hai", "query", "paneer"),
        ("biryani banane ke liye kya lagega", "query", "biryani banane liye lagega"),
    ]

    all_pass = True
    for text, expected_action, expected_entity in test_cases:
        start = time.time()
        intent = fast_extract_intent(text)
        elapsed_us = (time.time() - start) * 1_000_000

        if intent is None:
            print(f"  ❌ '{text}' → None (expected {expected_action}:{expected_entity})")
            all_pass = False
            continue

        action_ok = intent["action"] == expected_action
        entity_ok = intent["entity"] == expected_entity
        status = "✅" if (action_ok and entity_ok) else "⚠️"
        if not action_ok or not entity_ok:
            all_pass = False

        print(f"  {status} '{text}' → {intent['action']}:{intent['entity']} ({elapsed_us:.0f}µs)")

    if all_pass:
        print("  ✅ All intent extractions correct!")
    else:
        print("  ⚠️  Some extractions differ — check entity stopword list")

    # 3. Test Opposite Intent Detection
    print("\n[3/5] Testing opposite intent clash detection...")
    clash_tests = [
        ({"action": "add", "entity": "milk"}, {"action": "remove", "entity": "milk"}, True),
        ({"action": "add", "entity": "milk"}, {"action": "cancel", "entity": "milk"}, True),
        ({"action": "repeat", "entity": "order"}, {"action": "cancel", "entity": "order"}, True),
        ({"action": "add", "entity": "coffee"}, {"action": "add", "entity": "tea"}, False),
        ({"action": "add", "entity": "milk"}, {"action": "query", "entity": "milk"}, False),
    ]

    for intent_a, intent_b, expected_clash in clash_tests:
        is_clash = _are_opposite_intents(intent_a, intent_b)
        status = "✅" if (is_clash == expected_clash) else "❌"
        label = "BLOCKED" if is_clash else "allowed"
        print(f"  {status} {intent_a['action']}:{intent_a['entity']} vs {intent_b['action']}:{intent_b['entity']} → {label}")

    # 3b. Test Typo Fuzzy Matching
    print("\n[3b] Testing typo-resistant fuzzy matching...")
    from app.core.llm_cache import _fuzzy_match_action
    typo_tests = [
        ("ad", "add"),        # Missing letter
        ("addd", "add"),      # Extra letter
        ("remov", "remove"),  # Missing letter
        ("cancl", None),      # Too mangled (2 edits on 6-char word → allowed=2, might match)
        ("aad", "add"),       # Transposed
    ]
    for typo, expected in typo_tests:
        result = _fuzzy_match_action(typo)
        status = "✅" if result == expected else "⚠️"
        print(f"  {status} '{typo}' → {result} (expected: {expected})")

    # 3c. Test Multi-Intent Detection
    print("\n[3c] Testing multi-intent detection...")
    from app.core.llm_cache import _detect_multi_intent
    multi_tests = [
        ("milk add karo aur bread cancel karo", True),   # Two actions via 'aur'
        ("milk add karo", False),                         # Single intent
        ("coffee aur chai", False),                       # 'aur' but same action (no action words in parts)
        ("milk hata do and rice daal do", True),          # Two actions via 'and'
    ]
    for text, expected in multi_tests:
        result = _detect_multi_intent(text)
        status = "✅" if result == expected else "❌"
        label = "MULTI" if result else "SINGLE"
        print(f"  {status} '{text}' → {label}")

    # 3d. Test Entity Normalization Against Catalog
    print("\n[3d] Testing entity normalization against catalog...")
    from app.core.llm_cache import normalize_entity_to_catalog
    mock_catalog = [
        {"name": "Nescafe Classic Coffee 50g"},
        {"name": "Amul Taaza Toned Milk 500ml"},
        {"name": "Aashirvaad Atta 5kg"},
        {"name": "Britannia Bread"},
    ]
    norm_tests = [
        ("cofee", "nescafe classic coffee 50g"),      # Typo → catalog match
        ("milk", "amul taaza toned milk 500ml"),        # Generic → specific catalog
        ("bread", "britannia bread"),                    # Generic → catalog
    ]
    for entity, expected_contains in norm_tests:
        result = normalize_entity_to_catalog(entity, mock_catalog)
        status = "✅" if expected_contains in result.lower() else "⚠️"
        print(f"  {status} '{entity}' → '{result}'")

    # 4. Test Cache Round-Trip
    print("\n[4/5] Testing intent-based cache round-trip...")
    from app.core.llm_cache import get_llm_cache
    cache = get_llm_cache()

    # Store with one phrasing
    test_response = {"action": "add", "product_name": "coffee", "quantity": 1}
    await cache.set("coffee add karo", "test", test_response, context_hash="setup_test", ttl=60)

    # Retrieve with SAME intent, DIFFERENT phrasing
    result = await cache.get("mujhe coffee chahiye", "test", context_hash="setup_test")
    if result and result.get("product_name") == "coffee":
        print("  ✅ Intent cache HIT: 'mujhe coffee chahiye' matched 'coffee add karo'")
    else:
        print(f"  ⚠️  Intent cache MISS — result: {result}")
        print("     (Expected: both phrases extract intent add:coffee)")

    # Verify opposite intent is BLOCKED
    result_cancel = await cache.get("coffee cancel karo", "test", context_hash="setup_test")
    if result_cancel is None:
        print("  ✅ Opposite intent BLOCKED: 'coffee cancel karo' did NOT hit 'add:coffee' cache")
    else:
        print("  ❌ CRITICAL: 'coffee cancel karo' returned cached 'add' response!")

    # Cleanup
    exact_key = cache._exact_key("coffee add karo", "test", "setup_test")
    await RedisClient.delete(exact_key)

    # 5. Test Key Isolation
    print("\n[5/5] Testing key isolation...")
    from app.core.llm_cache import LLMCache
    key_add = LLMCache._intent_key({"action": "add", "entity": "coffee"}, "intent", "store1")
    key_remove = LLMCache._intent_key({"action": "remove", "entity": "coffee"}, "intent", "store1")
    key_add_other = LLMCache._intent_key({"action": "add", "entity": "coffee"}, "intent", "store2")

    print(f"  add:coffee (store1)    → {key_add}")
    print(f"  remove:coffee (store1) → {key_remove}")
    print(f"  add:coffee (store2)    → {key_add_other}")

    if key_add != key_remove:
        print("  ✅ add ≠ remove (different action → different key)")
    else:
        print("  ❌ CRITICAL: add and remove share the same key!")

    if key_add != key_add_other:
        print("  ✅ store1 ≠ store2 (different context → different key)")
    else:
        print("  ❌ Different stores share the same key!")

    # Summary
    stats = cache.get_stats()
    print(f"\n{'=' * 60}")
    print(f"  ✅ LLM Intent-Based Cache setup complete!")
    print(f"")
    print(f"  Cache stats: {json.dumps(stats)}")
    print(f"")
    print(f"  Look for these log messages:")
    print(f"    ⚡ LLM Cache EXACT HIT   — identical query")
    print(f"    🎯 LLM Cache INTENT HIT  — same intent, different words")
    print(f"    🛑 LLM Cache CLASH BLOCKED — opposite intent caught!")
    print(f"    💾 LLM Cache SET          — new entry stored")
    print(f"{'=' * 60}")

    await RedisClient.disconnect()
    return True


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
