import asyncio
import sys
import os
import logging
import traceback

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def test_core_services():
    """Test core services functionality"""
    print("\nTesting Core Services...")
    try:
        from core.core_engine.engine import get_core_engine
        from core.services.life_simulation.service import get_life_simulation_service
        
        # 1. Test Core Engine Initialization
        engine = get_core_engine()
        print("✓ Core Engine initialized")
        
        # 2. Test Life Simulation Service
        life_sim = get_life_simulation_service()
        await life_sim.start()
        print("✓ Life Simulation Service started")
        
        state = life_sim.get_state()
        print(f"✓ Life Simulation State retrieved: {state.keys()}")
        
        if not state.get('is_running'):
            raise Exception("Life Simulation is not running after start()")
            
        await life_sim.stop()
        print("✓ Life Simulation Service stopped")
        
        return True
    except Exception as e:
        print(f"❌ Core Services Test Failed: {e}")
        traceback.print_exc()
        return False

async def test_mvp_core_services():
    """Test MVP core services functionality"""
    print("\nTesting MVP Core Services...")
    try:
        from mvp_core.core import get_core_engine
        from mvp_core.services.life_simulation.service import get_life_simulation_service
        
        # 1. Test Core Engine
        engine = get_core_engine()
        print("✓ MVP Core Engine initialized")
        
        # 2. Test Life Simulation
        life_sim = get_life_simulation_service()
        await life_sim.start()
        print("✓ MVP Life Simulation Service started")
        
        state = life_sim.get_state()
        print(f"✓ MVP Life Simulation State retrieved: {state.keys()}")
        
        if not state.get('is_running'):
            raise Exception("MVP Life Simulation is not running after start()")
            
        await life_sim.stop()
        print("✓ MVP Life Simulation Service stopped")
        
        return True
    except Exception as e:
        print(f"❌ MVP Core Services Test Failed: {e}")
        traceback.print_exc()
        return False

async def main():
    print("="*50)
    print("STARTING RUNTIME CHECK")
    print("="*50)
    
    core_success = await test_core_services()
    mvp_success = await test_mvp_core_services()
    
    print("\n" + "="*50)
    print("SUMMARY")
    print("="*50)
    print(f"Core Services: {'✅ PASS' if core_success else '❌ FAIL'}")
    print(f"MVP Core Services: {'✅ PASS' if mvp_success else '❌ FAIL'}")
    
    if core_success and mvp_success:
        print("\n✅ ALL RUNTIME CHECKS PASSED")
    else:
        print("\n❌ SOME CHECKS FAILED")

if __name__ == "__main__":
    asyncio.run(main())
