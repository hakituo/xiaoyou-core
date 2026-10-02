import os
import sys
import time

def build_audio_processor():
    build_dir = "build"
    if not os.path.exists(build_dir):
        os.makedirs(build_dir)
    
    os.chdir(build_dir)
    print("Configuring CMake for cpp_audio_processor...")
    os.system("cmake ..")
    print("Building project...")
    os.system("cmake --build . --config Release")
    
    print("\n--- Build Complete ---")
    
    # Run test
    sys.path.append(os.path.join(os.path.abspath("."), "Release"))
    try:
        import audio_processor_py
        import numpy as np
        
        # Initialize VAD (Sample Rate: 16000Hz, Energy Threshold: 0.05)
        vad = audio_processor_py.AudioVAD(sample_rate=16000, energy_threshold=0.05)
        
        print("\n[SUCCESS] Imported audio_processor_py correctly.")
        
        # Generate Dummy Audio Data
        # 1. Silence (RMS ~ 0.0) -> 1 second
        silence_audio = np.zeros(16000, dtype=np.int16)
        
        # 2. Loud Noise / Speech (RMS > 0.05) -> 1 second
        speech_audio = np.random.randint(-15000, 15000, 16000, dtype=np.int16)
        
        # Combine: Silence + Speech + Silence = 3 seconds total
        combined_audio = np.concatenate([silence_audio, speech_audio, silence_audio])
        
        print(f"Original audio size: {len(combined_audio)} samples (3.0 seconds)")
        
        # Benchmarking
        start = time.perf_counter()
        
        # The C++ function directly accepts the numpy array via Pybind11 memory view
        clean_audio = vad.remove_silence(combined_audio, frame_ms=30)
        
        end = time.perf_counter()
        
        print(f"Processed audio size: {len(clean_audio)} samples (~1.0 second)")
        print(f"Processing time: {(end-start)*1000:.3f} ms")
        print("C++ successfully removed the silence and kept the speech!")
        
    except ImportError as e:
        print(f"[ERROR] Failed to import audio_processor_py: {e}")

if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    build_audio_processor()
