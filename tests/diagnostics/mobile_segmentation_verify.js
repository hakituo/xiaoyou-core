
// Mock implementation of utils/text.ts functions for testing
function isRetractionSegment(value) {
  return /^(\（[\s\S]*\）|\([\s\S]*\))$/.test(value.trim());
}

function segmentByRetractionOnly(text) {
  if (!text) return [];
  const regex = /（[\s\S]*?）|\([\s\S]*?\)/g;
  const segments = [];
  let lastIndex = 0;
  let match = null;

  while ((match = regex.exec(text)) !== null) {
    const start = match.index;
    const before = text.slice(lastIndex, start).trim();
    if (before.length > 0) {
      segments.push(before);
    }
    segments.push(match[0]);
    lastIndex = regex.lastIndex;
  }

  const tail = text.slice(lastIndex).trim();
  if (tail.length > 0) {
    segments.push(tail);
  }

  return segments;
}

// Test Data
const testCases = [
  {
    name: "Standard Retraction + Text",
    input: "(从低功耗监听中恢复) 嗯？\n(轻声) 怎么了？",
    hasRichPayload: true,
    expectedSegments: 4
  },
  {
    name: "Only Text",
    input: "你好，世界。",
    hasRichPayload: false,
    expectedSegments: 1
  },
  {
    name: "Only Retraction",
    input: "(Thinking...)",
    hasRichPayload: true,
    expectedSegments: 1
  }
];

console.log("=== Mobile Segmentation Verification ===\n");

let passed = 0;
let failed = 0;

testCases.forEach(test => {
  console.log(`Test: ${test.name}`);
  console.log(`Input: ${JSON.stringify(test.input)}`);
  
  const segments = segmentByRetractionOnly(test.input);
  console.log(`Segments: ${JSON.stringify(segments)}`);
  
  if (segments.length !== test.expectedSegments) {
    console.error(`FAIL: Expected ${test.expectedSegments} segments, got ${segments.length}`);
    failed++;
  } else {
    // Verify Payload Logic
    const firstNormalIndex = segments.findIndex(seg => !isRetractionSegment(seg));
    const baseIndex = firstNormalIndex === -1 ? 0 : firstNormalIndex;
    
    console.log(`Base Index (Main Payload Holder): ${baseIndex}`);
    
    segments.forEach((seg, i) => {
        const isRetract = isRetractionSegment(seg);
        const isMainPayloadHolder = (i === baseIndex);
        const hasPayload = isMainPayloadHolder; // Simplified logic mimicking MobileApp.tsx
        
        console.log(`  Segment ${i}: "${seg}" | IsRetract: ${isRetract} | HasPayload: ${hasPayload}`);
        
        if (test.hasRichPayload) {
            if (isRetract && hasPayload) {
                 console.error(`FAIL: Retraction segment ${i} should NOT have payload`);
                 failed++;
            }
            if (!isRetract && !hasPayload && i !== baseIndex) {
                 // If there are multiple normal segments, only one should have payload
                 // This is correct behavior now
                 console.log(`    (Correctly skipped payload for secondary normal segment)`);
            }
        }
    });
    
    console.log("PASS\n");
    passed++;
  }
});

console.log(`\nResult: ${passed} Passed, ${failed} Failed`);
if (failed > 0) process.exit(1);
