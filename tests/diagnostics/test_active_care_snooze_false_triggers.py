"""
Bug Condition Exploration Test for Active Care False Triggers

**Validates: Requirements 2.1, 2.2, 2.3, 2.4**

This test is designed to FAIL on unfixed code to confirm the bug exists.
The bug: Normal conversational messages with casual sleep/time mentions are 
incorrectly classified as ACTIVE_CARE_SNOOZE intent.

CRITICAL: This test MUST FAIL on unfixed code - failure confirms the bug exists.
DO NOT attempt to fix the test or the code when it fails.

Property 1: Fault Condition - False ACTIVE_CARE_SNOOZE Classification for Casual Sleep Mentions

For any user message where the bug condition holds (mentions sleep/time in passing 
but lacks explicit snooze request), the intent classifier SHALL classify it as NONE 
intent and NOT trigger the Active Care snooze action.
"""

import asyncio
import sys
import os

# Add project root to path to avoid circular imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.services.intent.service import classify_intent


# Test cases from the bug report - these should return NONE but currently return ACTIVE_CARE_SNOOZE
BUG_CONDITION_CASES = [
    # Example 1: Casual mention of waking up time
    {
        "text": "我六点起的好像，然后起来之后就一直在修你",
        "description": "Casual mention of waking up at 6am, no snooze request",
        "expected_intent": "NONE",
        "bug_condition": True,
    },
    # Example 2: Ambiguous sleep reference
    {
        "text": "想睡又不是会睡，而且你干嘛老是回这么多",
        "description": "Ambiguous sleep reference, no snooze request",
        "expected_intent": "NONE",
        "bug_condition": True,
    },
    # Example 3: Time mention in passing
    {
        "text": "我现在要去吃饭了，一会儿回来",
        "description": "Time mention in passing (一会儿), but about returning, not snoozing",
        "expected_intent": "NONE",
        "bug_condition": True,
    },
    # Example 4: Sleep word in non-snooze context
    {
        "text": "我昨晚睡得很好，今天精神不错",
        "description": "Past tense sleep mention, no snooze request",
        "expected_intent": "NONE",
        "bug_condition": True,
    },
    # Example 5: Time-related but not a delay request
    {
        "text": "我两小时前就起床了",
        "description": "Time mention (两小时) but past tense, not a delay request",
        "expected_intent": "NONE",
        "bug_condition": True,
    },
]


# Legitimate snooze requests - these should continue to work correctly
LEGITIMATE_SNOOZE_CASES = [
    {
        "text": "两小时后再提醒我",
        "description": "Explicit snooze request with time",
        "expected_intent": "ACTIVE_CARE_SNOOZE",
        "bug_condition": False,
    },
    {
        "text": "过一会再叫我",
        "description": "Explicit snooze request",
        "expected_intent": "ACTIVE_CARE_SNOOZE",
        "bug_condition": False,
    },
    {
        "text": "稍后再找我",
        "description": "Explicit snooze request",
        "expected_intent": "ACTIVE_CARE_SNOOZE",
        "bug_condition": False,
    },
    {
        "text": "晚点提醒我",
        "description": "Explicit snooze request",
        "expected_intent": "ACTIVE_CARE_SNOOZE",
        "bug_condition": False,
    },
]


async def test_bug_condition_exploration():
    """
    Bug Condition Exploration Test
    
    CRITICAL: This test is EXPECTED TO FAIL on unfixed code.
    Failure confirms the bug exists.
    
    This test checks that messages with casual sleep/time mentions are 
    incorrectly classified as ACTIVE_CARE_SNOOZE on unfixed code.
    
    After the fix is implemented, this test should PASS.
    """
    print("\n" + "=" * 80)
    print("BUG CONDITION EXPLORATION TEST")
    print("Testing: Active Care False Triggers - Casual Sleep Mentions")
    print("=" * 80)
    
    failures = []
    counterexamples = []
    
    for case in BUG_CONDITION_CASES:
        text = case["text"]
        expected = case["expected_intent"]
        description = case["description"]
        
        print(f"\n--- Testing Bug Condition Case ---")
        print(f"Input: {text}")
        print(f"Description: {description}")
        print(f"Expected (after fix): {expected}")
        
        result = await classify_intent(
            text=text,
            candidates=["ACTIVE_CARE_SNOOZE", "NONE"]
        )
        
        actual_intent = result.get("intent", "NONE")
        confidence = result.get("confidence", 0.0)
        raw = result.get("raw", "")
        
        print(f"Actual: {actual_intent}")
        print(f"Confidence: {confidence:.3f}")
        print(f"Raw: {raw}")
        
        # On unfixed code, we expect these to be misclassified as ACTIVE_CARE_SNOOZE
        # After fix, they should be NONE
        if actual_intent != expected:
            failure_msg = (
                f"COUNTEREXAMPLE FOUND (Bug Confirmed):\n"
                f"  Input: {text}\n"
                f"  Description: {description}\n"
                f"  Expected: {expected}\n"
                f"  Actual: {actual_intent}\n"
                f"  Confidence: {confidence:.3f}\n"
                f"  Raw: {raw}\n"
            )
            failures.append(failure_msg)
            counterexamples.append({
                "text": text,
                "description": description,
                "expected": expected,
                "actual": actual_intent,
                "confidence": confidence,
                "raw": raw,
            })
            print("❌ BUG DETECTED: Misclassified as ACTIVE_CARE_SNOOZE")
        else:
            print("✓ Correctly classified (bug may be fixed)")
    
    print("\n" + "=" * 80)
    print("BUG CONDITION EXPLORATION RESULTS")
    print("=" * 80)
    
    if counterexamples:
        print(f"\n✓ Bug Confirmed: Found {len(counterexamples)} counterexample(s)")
        print("\nCounterexamples (proving bug exists):")
        for i, ce in enumerate(counterexamples, 1):
            print(f"\n{i}. {ce['description']}")
            print(f"   Input: {ce['text']}")
            print(f"   Expected: {ce['expected']}, Got: {ce['actual']}")
            print(f"   Confidence: {ce['confidence']:.3f}, Raw: {ce['raw']}")
        
        print("\n" + "=" * 80)
        print("CONCLUSION: Bug exists - casual sleep mentions trigger false positives")
        print("=" * 80)
        
        return False  # Test fails to indicate bug exists
    else:
        print("\n⚠ No counterexamples found - bug may already be fixed or test needs adjustment")
        print("=" * 80)
        return True  # Test passes - bug may be fixed


async def test_legitimate_snooze_preservation():
    """
    Preservation Test - Verify legitimate snooze requests still work
    
    This test should PASS on both unfixed and fixed code.
    It ensures we don't break existing functionality.
    """
    print("\n" + "=" * 80)
    print("PRESERVATION TEST - Legitimate Snooze Requests")
    print("=" * 80)
    
    failures = []
    
    for case in LEGITIMATE_SNOOZE_CASES:
        text = case["text"]
        expected = case["expected_intent"]
        description = case["description"]
        
        print(f"\n--- Testing Legitimate Snooze Case ---")
        print(f"Input: {text}")
        print(f"Description: {description}")
        print(f"Expected: {expected}")
        
        result = await classify_intent(
            text=text,
            candidates=["ACTIVE_CARE_SNOOZE", "NONE"]
        )
        
        actual_intent = result.get("intent", "NONE")
        confidence = result.get("confidence", 0.0)
        raw = result.get("raw", "")
        
        print(f"Actual: {actual_intent}")
        print(f"Confidence: {confidence:.3f}")
        print(f"Raw: {raw}")
        
        if actual_intent != expected:
            failure_msg = (
                f"REGRESSION DETECTED:\n"
                f"  Input: {text}\n"
                f"  Description: {description}\n"
                f"  Expected: {expected}\n"
                f"  Actual: {actual_intent}\n"
                f"  Confidence: {confidence:.3f}\n"
            )
            failures.append(failure_msg)
            print("❌ REGRESSION: Legitimate snooze not detected")
        else:
            print("✓ Correctly classified")
    
    print("\n" + "=" * 80)
    print("PRESERVATION TEST RESULTS")
    print("=" * 80)
    
    if failures:
        print(f"\n❌ REGRESSION: {len(failures)} legitimate snooze case(s) failed")
        return False
    else:
        print("\n✓ All legitimate snooze requests correctly classified")
        print("=" * 80)
        return True


async def main():
    """Main test runner"""
    print("\n" + "=" * 80)
    print("ACTIVE CARE FALSE TRIGGERS - BUG CONDITION EXPLORATION")
    print("=" * 80)
    
    results = []
    
    # Run bug condition exploration test
    try:
        result1 = await test_bug_condition_exploration()
        results.append(("Bug Condition Exploration", result1))
    except Exception as e:
        print(f"\n❌ Bug condition exploration failed with exception: {e}")
        import traceback
        traceback.print_exc()
        results.append(("Bug Condition Exploration", False))
    
    # Run preservation test
    try:
        result2 = await test_legitimate_snooze_preservation()
        results.append(("Legitimate Snooze Preservation", result2))
    except Exception as e:
        print(f"\n❌ Preservation test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        results.append(("Legitimate Snooze Preservation", False))
    
    # Summary
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    
    for test_name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    print("\n" + "=" * 80)
    
    # For bug exploration, we expect the first test to fail
    bug_test_failed = not results[0][1]
    preservation_passed = results[1][1]
    
    if bug_test_failed and preservation_passed:
        print("✓ BUG CONFIRMED: Casual sleep mentions trigger false positives")
        print("  - Bug condition test failed as expected (bug exists)")
        print("  - Preservation test passed (legitimate snoozes still work)")
        print("\nNext step: Implement the fix as described in design.md")
    elif not bug_test_failed and preservation_passed:
        print("⚠ BUG MAY BE FIXED: All tests passed")
        print("  - Bug condition test passed (no false positives detected)")
        print("  - Preservation test passed (legitimate snoozes still work)")
    else:
        print("❌ UNEXPECTED RESULTS: Check test implementation")
    
    print("=" * 80)
    
    return bug_test_failed and preservation_passed


if __name__ == "__main__":
    # Allow running directly for debugging
    try:
        success = asyncio.run(main())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
