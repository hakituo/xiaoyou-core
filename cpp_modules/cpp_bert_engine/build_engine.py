import os

# Configure build with CMake
# This will build the C++ BERT engine using the existing setup

def build_engine():
    build_dir = "build"
    if not os.path.exists(build_dir):
        os.makedirs(build_dir)
    
    os.chdir(build_dir)
    print("Configuring CMake for cpp_bert_engine...")
    os.system("cmake ..")
    print("Building project...")
    os.system("cmake --build . --config Release")
    
    print("\n--- Build Complete ---")
    print("To test the engine, you can run: python ../test_engine.py")

if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    build_engine()
