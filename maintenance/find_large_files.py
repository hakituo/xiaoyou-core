import subprocess


def get_large_files(limit_mb=10):
    limit_bytes = limit_mb * 1024 * 1024
    process = subprocess.run(
        ["git", "rev-list", "--objects", "--all"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="ignore",
        check=False,
    )
    if process.returncode != 0:
        raise RuntimeError(process.stderr.strip() or "git rev-list 执行失败")

    objects = process.stdout.splitlines()

    print(f"Scanning {len(objects)} objects...")

    large_files = []

    # Batch processing could be faster but let's try simple loop first or batch via cat-file
    # We use git cat-file --batch-check

    process_batch = subprocess.Popen(
        ["git", "cat-file", "--batch-check=%(objectsize) %(objectname) %(rest)"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="ignore",
    )

    # Map SHA to Path
    sha_to_path = {}
    for line in objects:
        parts = line.split(maxsplit=1)
        if len(parts) == 2:
            sha_to_path[parts[0]] = parts[1]
        else:
            sha_to_path[parts[0]] = "no-path"

    input_str = "\n".join([obj.split()[0] for obj in objects])
    stdout, _ = process_batch.communicate(input=input_str)

    for line in stdout.splitlines():
        parts = line.split(maxsplit=2)
        if len(parts) < 2:
            continue
        size = int(parts[0])
        sha = parts[1]
        path = sha_to_path.get(sha, "unknown")

        if size > limit_bytes:
            large_files.append((size, sha, path))

    large_files.sort(key=lambda x: x[0], reverse=True)

    print(f"Found {len(large_files)} files larger than {limit_mb}MB:")
    for size, sha, path in large_files[:50]:
        print(f"{size / 1024 / 1024:.2f} MB - {path} ({sha})")


if __name__ == "__main__":
    get_large_files(10)
