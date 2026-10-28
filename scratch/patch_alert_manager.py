with open('monitor_app/alert_manager.py', 'r', encoding='utf-8') as f:
    text = f.read()

target1 = """            # CRITICAL and HIGH severity confirm immediately without lag
            if self.highest_severity in ("CRITICAL", "HIGH") or self.pending_duration <= 0.0:"""

repl1 = """            # CRITICAL, HIGH, and MEDIUM (contraband) severity confirm immediately without lag
            if self.highest_severity in ("CRITICAL", "HIGH", "MEDIUM") or self.pending_duration <= 0.0:"""

target2 = """            if self.highest_severity in ("CRITICAL", "HIGH") or (now - self.first_detected >= self.pending_duration):"""

repl2 = """            if self.highest_severity in ("CRITICAL", "HIGH", "MEDIUM") or (now - self.first_detected >= self.pending_duration):"""

assert target1 in text, "target1 not found"
assert target2 in text, "target2 not found"

text = text.replace(target1, repl1, 1).replace(target2, repl2, 1)

with open('monitor_app/alert_manager.py', 'w', encoding='utf-8', newline='') as f:
    f.write(text)

print("SUCCESS: alert_manager.py patched")

