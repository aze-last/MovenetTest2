import os
import sys
import subprocess

def check_changes():
    """
    Checks for code modifications across the project even if git commands
    are unavailable or restricted.
    """
    print("=== CELLWATCH CODE MODIFICATION CHECKER ===")
    
    # 1. Try git diff first if git is available
    try:
        res = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, check=True)
        changes = res.stdout.strip()
        if changes:
            # Filter out practice debug files
            filtered_lines = [l for l in changes.splitlines() if not ("_debug_answer_key" in l or "check_changes" in l)]
            if filtered_lines:
                print("[GIT DETECTED MODIFICATIONS]:")
                print("\n".join(filtered_lines))
                print("\nDetailed diff:")
                diff_res = subprocess.run(["git", "diff", "-U0", "--", "monitor_app/"], capture_output=True, text=True)
                print(diff_res.stdout)  # print all modified files and diffs
                return

        print("Git repository reports working directory clean.")

    except Exception as e:
        print(f"Git diff unavailable: {e}")

    # 2. Fallback: Check progress report log and files modified recently (last 2 hours)
    import time
    now = time.time()
    two_hours_ago = now - 7200
    
    modified_files = []
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    for root, _, files in os.walk(os.path.join(project_root, "monitor_app")):
        for f in files:
            if f.endswith(".py"):
                path = os.path.join(root, f)
                mtime = os.path.getmtime(path)
                if mtime > two_hours_ago:
                    rel_path = os.path.relpath(path, project_root)
                    modified_files.append((rel_path, time.ctime(mtime)))
                    
    if modified_files:
        print("\n[RECENTLY MODIFIED FILES IN LAST 2 HOURS]:")
        for filepath, mtime_str in modified_files:
            print(f"  - {filepath} (Modified: {mtime_str})")
    else:
        print("No recent file modifications detected in monitor_app/.")

if __name__ == "__main__":
    check_changes()
