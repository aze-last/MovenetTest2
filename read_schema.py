import sqlite3
import os

app_state_path = os.path.abspath('monitor_app/app_state.db')
benchmark_path = os.path.abspath('monitor_app/benchmark.db')

for path, name in [(app_state_path, 'app_state.db'), (benchmark_path, 'benchmark.db')]:
    print(f'Schema of {name}:')
    try:
        conn = sqlite3.connect(path)
        cur = conn.cursor()
        cur.execute("SELECT sql FROM sqlite_master WHERE type='table';")
        for r in cur.fetchall():
            print(r[0])
    except Exception as e:
        print('Error:', e)
