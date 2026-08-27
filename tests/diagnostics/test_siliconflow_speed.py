import sys, asyncio, time
sys.path.insert(0, 'd:/AI/xiaoyou-core')
from core.services.scheduler.task.task_scheduler import get_global_scheduler

async def test():
    scheduler = get_global_scheduler()
    prompt = '请用JSON格式回答：{"answer": "hello"}'

    models = [
        'cloud:deepseek:deepseek-v4-flash',
        'cloud:siliconflow:deepseek-ai/DeepSeek-V4-Flash',
        'cloud:siliconflow:Pro/zai-org/GLM-5.1',
    ]

    for model in models:
        print(f'\n=== {model} ===')
        start = time.time()
        response = ''
        chunk_count = 0

        async def _run():
            nonlocal response, chunk_count
            async for chunk in scheduler.submit_llm_task(prompt, max_tokens=100, temperature=0.3, model_hint=model):
                chunk_count += 1
                if isinstance(chunk, str):
                    response += chunk
                elif isinstance(chunk, dict):
                    if chunk.get('content'):
                        response += chunk['content']
                    if chunk.get('error'):
                        print(f'  ERROR: {chunk["error"]}')

        try:
            await asyncio.wait_for(_run(), timeout=30.0)
        except asyncio.TimeoutError:
            print('  TIMEOUT (30s)')
        except Exception as e:
            print(f'  Exception: {e}')

        elapsed = time.time() - start
        print(f'  Time: {elapsed:.2f}s | Chunks: {chunk_count} | Response: {response[:150]}')

asyncio.run(test())
