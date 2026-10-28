with open("monitor_app/central_inference.py", "r", encoding="utf-8") as f:
    code = f.read()

target = """        for det in self._contraband_for_render(detections):
            name = det.get("name", "Unknown")
            track_id = det.get("track_id", -1)
            conf = float(det.get("confidence", 0.0))
            x1, y1, x2, y2 = map(int, det.get("box", [0, 0, 0, 0]))
            alert_color = (0, 0, 255)

            # Professional CCTV frame with corner brackets (Anti-Aliased with solid stroke)
            cv2.rectangle(frame, (x1, y1), (x2, y2), alert_color, base_thick, lineType=cv2.LINE_AA)
            c_len = min(20, max(8, (x2 - x1) // 4), max(8, (y2 - y1) // 4))
            cv2.line(frame, (x1, y1), (x1 + c_len, y1), alert_color, bracket_thick, lineType=cv2.LINE_AA)
            cv2.line(frame, (x1, y1), (x1, y1 + c_len), alert_color, bracket_thick, lineType=cv2.LINE_AA)
            cv2.line(frame, (x2, y1), (x2 - c_len, y1), alert_color, bracket_thick, lineType=cv2.LINE_AA)
            cv2.line(frame, (x2, y1), (x2, y1 + c_len), alert_color, bracket_thick, lineType=cv2.LINE_AA)
            cv2.line(frame, (x1, y2), (x1 + c_len, y2), alert_color, bracket_thick, lineType=cv2.LINE_AA)
            cv2.line(frame, (x1, y2), (x1, y2 - c_len), alert_color, bracket_thick, lineType=cv2.LINE_AA)
            cv2.line(frame, (x2, y2), (x2 - c_len, y2), alert_color, bracket_thick, lineType=cv2.LINE_AA)
            cv2.line(frame, (x2, y2), (x2, y2 - c_len), alert_color, bracket_thick, lineType=cv2.LINE_AA)

            label_text = f"ALERT: {name.upper()} {int(conf*100)}% (THR: >=30%) ID:{track_id}" if conf > 0 else f"ALERT: {name.upper()} (ID: {track_id})"
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.50
            (tw, th), _ = cv2.getTextSize(label_text, font, font_scale, 2)
            badge_h = th + 8
            badge_w = tw + 10
            if y1 - badge_h >= 0:
                by1 = y1 - badge_h
                by2 = y1
            else:
                by1 = y1
                by2 = min(frame.shape[0], y1 + badge_h)
            bx1 = max(0, x1)
            bx2 = min(frame.shape[1], bx1 + badge_w)

            cv2.rectangle(frame, (bx1, by1), (bx2, by2), (20, 20, 20), -1)
            cv2.rectangle(frame, (bx1, by1), (bx2, by2), alert_color, base_thick, lineType=cv2.LINE_AA)
            cv2.putText(frame, label_text, (bx1 + 5, by2 - 5), font, font_scale, (0, 80, 255), 2, lineType=cv2.LINE_AA)"""

replacement = """        for det in self._contraband_for_render(detections):
            name = det.get("name", "Unknown")
            track_id = det.get("track_id", -1)
            conf = float(det.get("confidence", 0.0))
            x1, y1, x2, y2 = map(int, det.get("box", [0, 0, 0, 0]))

            is_dismissed = bool(det.get("dismissed"))
            if is_dismissed:
                alert_color = (139, 116, 100)  # Muted slate gray BGR
                text_color = (180, 180, 180)   # Light gray text
                label_text = f"{name.upper()} #{track_id} [DISMISSED]"
            else:
                alert_color = (0, 0, 255)      # Red BGR
                text_color = (0, 80, 255)       # Orange BGR
                label_text = f"ALERT: {name.upper()} {int(conf*100)}% (THR: >=30%) ID:{track_id}" if conf > 0 else f"ALERT: {name.upper()} (ID: {track_id})"

            # Professional CCTV frame with corner brackets (Anti-Aliased with solid stroke)
            cv2.rectangle(frame, (x1, y1), (x2, y2), alert_color, base_thick, lineType=cv2.LINE_AA)
            c_len = min(20, max(8, (x2 - x1) // 4), max(8, (y2 - y1) // 4))
            cv2.line(frame, (x1, y1), (x1 + c_len, y1), alert_color, bracket_thick, lineType=cv2.LINE_AA)
            cv2.line(frame, (x1, y1), (x1, y1 + c_len), alert_color, bracket_thick, lineType=cv2.LINE_AA)
            cv2.line(frame, (x2, y1), (x2 - c_len, y1), alert_color, bracket_thick, lineType=cv2.LINE_AA)
            cv2.line(frame, (x2, y1), (x2, y1 + c_len), alert_color, bracket_thick, lineType=cv2.LINE_AA)
            cv2.line(frame, (x1, y2), (x1 + c_len, y2), alert_color, bracket_thick, lineType=cv2.LINE_AA)
            cv2.line(frame, (x1, y2), (x1, y2 - c_len), alert_color, bracket_thick, lineType=cv2.LINE_AA)
            cv2.line(frame, (x2, y2), (x2 - c_len, y2), alert_color, bracket_thick, lineType=cv2.LINE_AA)
            cv2.line(frame, (x2, y2), (x2, y2 - c_len), alert_color, bracket_thick, lineType=cv2.LINE_AA)

            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.50
            (tw, th), _ = cv2.getTextSize(label_text, font, font_scale, 2)
            badge_h = th + 8
            badge_w = tw + 10
            if y1 - badge_h >= 0:
                by1 = y1 - badge_h
                by2 = y1
            else:
                by1 = y1
                by2 = min(frame.shape[0], y1 + badge_h)
            bx1 = max(0, x1)
            bx2 = min(frame.shape[1], bx1 + badge_w)

            cv2.rectangle(frame, (bx1, by1), (bx2, by2), (20, 20, 20), -1)
            cv2.rectangle(frame, (bx1, by1), (bx2, by2), alert_color, base_thick, lineType=cv2.LINE_AA)
            cv2.putText(frame, label_text, (bx1 + 5, by2 - 5), font, font_scale, text_color, 2, lineType=cv2.LINE_AA)"""

if target in code:
    code = code.replace(target, replacement)
elif target.replace("\n", "\r\n") in code:
    code = code.replace(target.replace("\n", "\r\n"), replacement.replace("\n", "\r\n"))

with open("monitor_app/central_inference.py", "w", encoding="utf-8") as f:
    f.write(code)

print("central_inference.py updated successfully!")

