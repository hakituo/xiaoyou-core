import sys
from collections import Counter

from core.tools.study.english.vocabulary_manager import get_vocabulary_manager

vm = get_vocabulary_manager()
words = vm.get_daily_words(limit=20)
print("total returned:", len(words))
print("status breakdown:", dict(Counter(w.get("status") for w in words)))
print("first 12 words (word | status | unknown_count):")
for w in words[:12]:
    print("  -", w.get("word"), "|", w.get("status"), "|", w.get("unknown_count"))

# 验证：不再按 unknown_count 降序钉死前排
counts = [w.get("unknown_count", 0) for w in words]
print("unknown_count sequence (should NOT be strictly descending):", counts[:12])

# 验证：同词不重复出现
seen = set()
dup = 0
for w in words:
    k = w.get("word", "").lower()
    if k in seen:
        dup += 1
    seen.add(k)
print("duplicate words in result:", dup)
