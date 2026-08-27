import asyncio
from aiohttp import web
from core.llm.openai_compat import OpenAIClient

# Mock Server
async def start_mock_server(port):
    async def sse_handler(request):
        response = web.StreamResponse(
            status=200,
            reason='OK',
            headers={'Content-Type': 'text/event-stream'}
        )
        await response.prepare(request)
        
        # Scenario 1: Standard SSE
        await response.write(b'data: {"choices": [{"delta": {"content": "Standard"}}]}\n\n')
        
        # Scenario 2: Broken SSE with raw newline inside JSON string
        # Client splits by \n. 
        # Line 1: data: {"choices": [{"delta": {"content": "Broken\n
        # Line 2: Newline"}}]}
        await response.write(b'data: {"choices": [{"delta": {"content": "Broken\nNewline"}}]}\n\n')

        # Scenario 3: JSON split across multiple data: lines (Non-standard but logic handles it)
        # Line 1: data: {"choices": [{"delta": {"content": "Split
        # Line 2: data: Data"}}]}
        # Note: My logic concatenates them.
        await response.write(b'data: {"choices": [{"delta": {"content": "Split')
        await response.write(b'Data"}}]}\n\n')

        # Scenario 4: The "DeepSeek [" Case?
        # Maybe it sends [ then raw newline?
        await response.write(b'data: {"choices": [{"delta": {"content": "["}}]}\n\n')
        await response.write(b'data: {"choices": [{"delta": {"content": "Thinking\nProcess"}}]}\n\n')

        await response.write(b'data: [DONE]\n\n')
        return response

    app = web.Application()
    app.router.add_post('/v1/chat/completions', sse_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, 'localhost', port)
    await site.start()
    return runner

async def test_client():
    port = 8099
    runner = await start_mock_server(port)
    
    client = OpenAIClient(api_key="fake", base_url=f"http://localhost:{port}/v1/chat/completions")
    messages = [{"role": "user", "content": "test"}]
    
    print("\n--- Starting Stream ---")
    collected = ""
    async for chunk in client.stream_chat(messages):
        if "content" in chunk:
            print(f"Chunk: {chunk['content']!r}")
            collected += chunk['content']
        if "error" in chunk:
            print(f"Error: {chunk['error']}")
            
    print(f"\n--- Full Content: {collected!r} ---")
    
    await client.shutdown()
    await runner.cleanup()
    
    expected = "StandardBroken\nNewlineSplitData[Thinking\nProcess"
    if collected == expected:
        print("SUCCESS: All chunks received correctly.")
    else:
        print(f"FAILURE: Expected {expected!r}, got {collected!r}")

    assert collected == expected, f"SSE 流式输出内容不匹配: 期望 {expected!r}, 得到 {collected!r}"

if __name__ == "__main__":
    asyncio.run(test_client())
