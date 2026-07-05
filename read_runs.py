import sqlite3
import os
import json

benchmark_path = os.path.abspath('monitor_app/benchmark.db')

try:
    conn = sqlite3.connect(benchmark_path)
    cur = conn.cursor()
    
    print('=== GOLDEN BASELINE (benchmark.db) ===')
    cur.execute("SELECT run_id, performance_score FROM runs WHERE is_golden_baseline = 1")
    res = cur.fetchone()
    if res:
        print(f"Run ID: {res[0]}, Score: {res[1]}")
    else:
        print('No golden baseline found.')
        
    print('\n=== LAST BENCHMARK RUN (benchmark.db) ===')
    cur.execute("SELECT run_id, performance_score FROM runs ORDER BY timestamp DESC LIMIT 1")
    res = cur.fetchone()
    if res:
        print(f"Run ID: {res[0]}, Score: {res[1]}")
    else:
        print('No runs found.')
        
except Exception as e:
    print('Error:', e)
