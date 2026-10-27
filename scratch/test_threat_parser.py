import sqlite3
import re

conn = sqlite3.connect('incidents.db')
c = conn.cursor()
c.execute('SELECT event_id, event_type FROM incidents ORDER BY LENGTH(event_type) DESC LIMIT 15')
rows = c.fetchall()

def parse_threats(raw_type):
    if not raw_type or not raw_type.strip():
        return []
    tokens = [t.strip() for t in re.split(r'[\+\n,]+', raw_type) if t.strip()]
    events = {}
    for tok in tokens:
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

    def get_category_info(name):
        n = name.lower()
        if any(w in n for w in ['knife', 'gun', 'weapon']):
            return 'danger', 'WEAPON'
        elif any(w in n for w in ['fight', 'aggressive', 'assault', 'violence']):
            return 'danger', 'VIOLENCE'
        elif any(w in n for w in ['cellphone', 'phone', 'contraband', 'cigarette']):
            return 'warning', 'CONTRABAND'
        elif any(w in n for w in ['movement', 'motion', 'running', 'fall', 'loiter']):
            return 'accent', 'BEHAVIOR'
        return 'neutral', 'ALERT'

    threats = []
    for name, data in sorted(events.items(), key=lambda x: (x[1]['max_conf'] or 0, x[1]['count']), reverse=True):
        cat, tag = get_category_info(name)
        count = data['count']
        max_c = data['max_conf']
        detail_parts = []
        if max_c is not None:
            detail_parts.append(f"Peak: {max_c}%")
        if count > 1:
            detail_parts.append(f"{count} frames")
        detail = " | ".join(detail_parts) if detail_parts else "Detected"
        threats.append({
            'name': name,
            'category': cat,
            'tag': tag,
            'count': count,
            'max_conf': max_c,
            'detail': detail
        })
    return threats

for r in rows:
    th = parse_threats(r[1])
    print(f"Incident: {r[0]} (raw len: {len(r[1])})")
    for t in th:
        print(f"  [{t['tag']}] {t['name']} -> {t['detail']} (cat: {t['category']})")
    print("-" * 50)

