import sqlite3
import os

app_state_path = os.path.abspath('monitor_app/app_state.db')
benchmark_path = os.path.abspath('monitor_app/benchmark.db')

for path, name in [(app_state_path, 'app_state.db'), (benchmark_path, 'benchmark.db')]:
    print(f'Tables in {name}:')
    try:
        conn = sqlite3.connect(path)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
        print([r[0] for r in cur.fetchall()])
    except Exception as e:
        print('Error:', e)
