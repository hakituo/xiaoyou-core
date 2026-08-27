
import unittest
import time
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from memory.weighted_memory_manager import WeightedMemoryManager

TEST_USER_ID = "test_user_persistence"
HISTORY_DIR = Path("d:/AI/xiaoyou-core/history")
WEIGHTED_DIR = HISTORY_DIR / "weighted"
SHORT_TERM_DIR = HISTORY_DIR / "short_term"

class TestShortTermPersistence(unittest.TestCase):
    def setUp(self):
        # Clean up previous test data
        self._clean_files()
        
        # Initialize manager with small short_term limit to force trimming
        self.manager = WeightedMemoryManager(
            user_id=TEST_USER_ID,
            max_short_term=2, # Very small window
            auto_save_interval=0
        )

    def tearDown(self):
        self._clean_files()

    def _clean_files(self):
        # Remove weighted files
        for root, dirs, files in os.walk(WEIGHTED_DIR):
            for f in files:
                if TEST_USER_ID in f:
                    try:
                        os.remove(os.path.join(root, f))
                    except Exception:
                        pass
        
        # Remove short term file
        short_file = SHORT_TERM_DIR / f"{TEST_USER_ID}_short.json"
        if short_file.exists():
            short_file.unlink()

    def test_all_memories_persisted(self):
        """Test that even trivial memories are persisted to weighted storage"""
        print("\nTesting trivial memory persistence...")
        
        # 1. Add a trivial memory
        content = "hi"
        print(f"Adding memory: '{content}'")
        self.manager.add_memory(content, role="user")
        
        # 2. Check if it's in weighted_memories (in memory)
        found = False
        for mem in self.manager.weighted_memories.values():
            if mem["content"] == content:
                found = True
                break
        self.assertTrue(found, "Trivial memory should be in weighted_memories dict")
        
        # 3. Save and check file
        self.manager.save_memory()
        
        # Wait for async save
        time.sleep(3)
        
        # Verify file existence (should be in 'uncategorized' or similar)
        # Note: 'hi' usually goes to uncategorized or daily depending on detection
        found_in_file = False
        for root, dirs, files in os.walk(WEIGHTED_DIR):
            for f in files:
                if TEST_USER_ID in f:
                    with open(os.path.join(root, f), 'r', encoding='utf-8') as jf:
                        data = jf.read()
                        if content in data:
                            found_in_file = True
                            print(f"Found memory in file: {os.path.join(root, f)}")
                            break
        
        self.assertTrue(found_in_file, "Trivial memory should be persisted in weighted files")

    def test_trimming_safety(self):
        """Test that trimming short_term doesn't lose data"""
        print("\nTesting trimming safety...")
        
        # Add 3 memories (limit is 2)
        msgs = ["msg1", "msg2", "msg3"]
        for m in msgs:
            self.manager.add_memory(m, role="user")
            
        # Manually trigger trim (usually happens in add_memory -> schedule_trim -> delayed_trim)
        # But add_memory schedules it async, so we call internal method directly
        self.manager._trim_short_term_memory()
        
        # Check short_term_memory size
        print(f"Short term size: {len(self.manager.short_term_memory)}")
        self.assertLessEqual(len(self.manager.short_term_memory), 2)
        
        # Check if 'msg1' (the oldest) is still in weighted_memories
        found_msg1 = False
        for mem in self.manager.weighted_memories.values():
            if mem["content"] == "msg1":
                found_msg1 = True
                break
        
        self.assertTrue(found_msg1, "Trimmed memory 'msg1' MUST still exist in weighted_memories")
        print("PASS: Data persisted despite short-term trimming.")

if __name__ == '__main__':
    unittest.main()
