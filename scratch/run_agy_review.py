import subprocess
import sys

with open("scratch/review_prompt.txt", "r", encoding="utf-8") as f:
    prompt = f.read()

print("[AGY-REVIEW] Starting agy code review...")
proc = subprocess.run(
    ["agy", "--mode", "plan", "--dangerously-skip-permissions", "--print", prompt],
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace"
)

print("[AGY-REVIEW] Return code:", proc.returncode)
print("[AGY-REVIEW] STDOUT:\n", proc.stdout)
if proc.stderr:
    print("[AGY-REVIEW] STDERR:\n", proc.stderr)

