import subprocess

def get_large_files(limit_mb=10):
    limit_bytes = limit_mb * 1024 * 1024
    cmd = "git rev-list --objects --all"
    process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding='utf-8', errors='ignore')
    objects = process.stdout.read().splitlines()
    
    print(f"Scanning {len(objects)} objects...")
    
    large_files = []
    
    # Batch processing could be faster but let's try simple loop first or batch via cat-file
    # We use git cat-file --batch-check
    
    cmd_batch = "git cat-file --batch-check=\"%(objectsize) %(objectname) %(rest)\""
    process_batch = subprocess.Popen(cmd_batch, shell=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE, encoding='utf-8', errors='ignore')
    
    # Map SHA to Path
    sha_to_path = {}
    for line in objects:
        parts = line.split(maxsplit=1)
        if len(parts) == 2:
            sha_to_path[parts[0]] = parts[1]
        else:
            sha_to_path[parts[0]] = "no-path"
            
    input_str = "\n".join([obj.split()[0] for obj in objects])
    stdout, stderr = process_batch.communicate(input=input_str)
    
    for line in stdout.splitlines():
        parts = line.split(maxsplit=2)
        if len(parts) < 2: continue
        size = int(parts[0])
        sha = parts[1]
        path = sha_to_path.get(sha, "unknown")
        
        if size > limit_bytes:
            large_files.append((size, sha, path))
            
    large_files.sort(key=lambda x: x[0], reverse=True)
    
    print(f"Found {len(large_files)} files larger than {limit_mb}MB:")
    for size, sha, path in large_files[:50]:
        print(f"{size/1024/1024:.2f} MB - {path} ({sha})")

if __name__ == "__main__":
    get_large_files(10)
