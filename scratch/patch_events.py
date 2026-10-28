with open('monitor_app/events.py', 'r', encoding='utf-8') as f:
    text = f.read()

target = """# Telemetry Event Names"""
replacement = """# Incident and Alert Event Names
INCIDENT_START = "INCIDENT_START"
INCIDENT_STOP = "INCIDENT_STOP"
DECISION_TRIGGER = "DECISION_TRIGGER"

# Telemetry Event Names"""

assert target in text, "target not found"
text = text.replace(target, replacement, 1)

with open('monitor_app/events.py', 'w', encoding='utf-8') as f:
    f.write(text)

print("Updated events.py successfully")

