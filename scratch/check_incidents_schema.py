import sqlite3
conn = sqlite3.connect('incidents.db')
cur = conn.cursor()
cur.execute("SELECT event_id, camera_id, timestamp_start, event_type, confidence_scores, review_status, video_path FROM incidents ORDER BY timestamp_start DESC LIMIT 3")
for row in cur.fetchall():
    print("---")
    print("event_id:", row[0])
    print("camera_id:", row[1])
    print("time:", row[2])
    print("event_type (first 100 chars):", str(row[3])[:100])
    print("status:", row[5])
    print("video_path:", row[6])
conn.close()

