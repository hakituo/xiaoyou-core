import logging
import asyncio
import time
import random
from mvp_core.domain.interfaces.base_interfaces import ImageGenInterface

logger = logging.getLogger("SyntheticImageAdapter")

class SyntheticImageAdapter(ImageGenInterface):
    def __init__(self, latency_mean: float = 2.0, latency_std: float = 0.5):
        self.latency_mean = latency_mean
        self.latency_std = latency_std

    async def generate_image(self, prompt: str, **kwargs) -> str:
        """
        Simulate image generation with CPU load.
        """
        logger.info(f"Generating synthetic image for prompt: {prompt[:20]}...")
        
        # Simulate latency
        delay = max(0.1, random.gauss(self.latency_mean, self.latency_std))
        
        # Simulate CPU load (optional: simple spin lock or math)
        # We use sleep to simulate I/O bound wait (GPU wait), 
        # and a bit of math for CPU overhead if needed.
        
        start = time.time()
        # Simulate 10% CPU work, 90% GPU wait
        cpu_time = delay * 0.1
        gpu_time = delay * 0.9
        
        # CPU Burn
        end_cpu = start + cpu_time
        while time.time() < end_cpu:
            _ = [x**2 for x in range(1000)]
            
        # GPU Wait
        await asyncio.sleep(gpu_time)
        
        logger.info(f"Synthetic image generation complete in {delay:.2f}s")
        return "synthetic_image.png"
