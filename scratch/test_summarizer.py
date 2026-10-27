import sqlite3
import re

conn = sqlite3.connect('incidents.db')
c = conn.cursor()
c.execute('SELECT DISTINCT event_type FROM incidents')
types = [r[0] for r in c.fetchall() if r[0]]

def parse_and_summarize_event_type(raw_type):
    if not raw_type or not raw_type.strip():
        return []
    tokens = [t.strip() for t in re.split(r'[\+\n]+', raw_type) if t.strip()]
    events = {}
    for tok in tokens:
        # Match pattern: 'Name (num%)' or 'Name (num% >= num%)' or just 'Name'
        m = re.match(r'^(.*?)(?:\s*\(\s*(\d+)%.*?\))?$', tok)
        if m:
            name = m.group(1).strip()
            conf_str = m.group(2)
            conf = int(conf_str) if conf_str else None
        else:
            name = tok
            conf = None
        
        clean_name = ' '.join(name.split())
        if not clean_name:
            continue
        if clean_name.lower() in ('cellphone', 'knife', 'alert'):
            clean_name = clean_name.capitalize()
            
        if clean_name not in events:
            events[clean_name] = {'count': 0, 'max_conf': None}
        events[clean_name]['count'] += 1
        if conf is not None:
            if events[clean_name]['max_conf'] is None or conf > events[clean_name]['max_conf']:
                events[clean_name]['max_conf'] = conf
                
    result = []
    for name, data in sorted(events.items(), key=lambda x: (x[1]['max_conf'] or 0, x[1]['count']), reverse=True):
        entry = {
            'name': name,
            'count': data['count'],
            'max_conf': data['max_conf'],
        }
        if data['max_conf'] is not None:
            if data['count'] > 1:
                entry['summary'] = f"{name} ({data['max_conf']}% | {data['count']}x)"
            else:
                entry['summary'] = f"{name} ({data['max_conf']}%)"
        else:
            if data['count'] > 1:
                entry['summary'] = f"{name} ({data['count']}x)"
            else:
                entry['summary'] = f"{name}"
        result.append(entry)
    return result

for t in sorted(types, key=len, reverse=True)[:8]:
    print(f"RAW (len {len(t)}): {t[:65]}...")
    summaries = parse_and_summarize_event_type(t)
    for s in summaries:
        print(f"   -> {s['summary']}")
    print("-" * 60)

