import sqlite3
import json
import os

app_state_path = os.path.abspath('monitor_app/app_state.db')
benchmark_path = os.path.abspath('monitor_app/benchmark.db')

print('=== GOLDEN BASELINE (app_state.db) ===')
try:
    conn = sqlite3.connect(app_state_path)
    cur = conn.cursor()
    cur.execute("SELECT config_json FROM ai_settings WHERE profile_name='golden_baseline'")
    res = cur.fetchone()
    if res:
        print(json.dumps(json.loads(res[0]), indent=2))
    else:
        # Check all ai_settings
        cur.execute("SELECT profile_name, config_json FROM ai_settings")
        all_res = cur.fetchall()
        print("No exact match. Dumping all ai_settings:")
        for r in all_res:
            print(r[0])
            print(json.dumps(json.loads(r[1]), indent=2))
except Exception as e:
    print('Error:', e)

print('\n=== LAST BENCHMARK RUN (benchmark.db) ===')
try:
    conn2 = sqlite3.connect(benchmark_path)
    cur2 = conn2.cursor()
    cur2.execute("SELECT manifest_json, score, verdict FROM runs ORDER BY id DESC LIMIT 1")
    res = cur2.fetchone()
    if res:
        print("Score:", res[1])
        print("Verdict:", res[2])
        print(json.dumps(json.loads(res[0]), indent=2))
    else:
        print('No runs found.')
except Exception as e:
    print('Error reading runs:', e)
