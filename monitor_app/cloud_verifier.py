"""
Cloud Verifier — optional internet AI second-opinion for incidents.

Design (GEMINI Rules 1,2,4,8 compliant):
- OFF by default (config.yaml cloud_verifier.enabled: false). Offline deployment unaffected.
- Local truth first: AlertManager still publishes INCIDENT_START + audio + recording
  synchronously. This module only enriches afterwards via EventBus("CLOUD_VERDICT").
- Never blocks UI / inference: only daemon-thread async entry points.
- Stdlib only (urllib, json, base64, threading, time). No new dependency (Rule 8).
- OpenAI Chat Completions compatible (xKiro: https://api.xkiro.com/v1).
  Auth: env XKIRO_API_KEY only. Never hardcode, never commit key.
- Rate-limited: max 1 call per incident + min_interval + cooldown. No per-frame calls.
- Fail-safe: timeout / 429 / no-key / http-error -> silent fallback to local verdict.

Payload: 1 cropped JPEG snapshot (base64 data URL) + event_type/severity.
NOT full video, NOT per-frame stream.
"""
import base64
import json
import os
import threading
import time
import urllib.request
import urllib.error


DEFAULT_BASE_URL = "https://api.xkiro.com/v1"
DEFAULT_MODEL = "vendor/model"
DEFAULT_TIMEOUT_S = 2.0
DEFAULT_MIN_INTERVAL_S = 10.0
MAX_JPEG_BYTES = 400_000  # cap snapshot size to bound tokens/cost


def _is_allowed_https_url(url):
    try:
        from urllib.parse import urlsplit
        p = urlsplit(str(url))
        return p.scheme.lower() == "https" and bool(p.hostname) and "@" not in str(url)
    except Exception:
        return False


def get_cloud_verifier_config():
    """Read engineering config. Returns dict with safe defaults (disabled)."""
    try:
        from monitor_app.config import get_config
        cfg = get_config("cloud_verifier") or {}
    except Exception:
        cfg = {}
    return {
        "enabled": bool(cfg.get("enabled", False)),
        "base_url": str(cfg.get("base_url", DEFAULT_BASE_URL)),
        "model": str(cfg.get("model", DEFAULT_MODEL)),
        "timeout_s": float(cfg.get("timeout_s", DEFAULT_TIMEOUT_S)),
        "min_interval_s": float(cfg.get("min_interval_s", DEFAULT_MIN_INTERVAL_S)),
        "max_image_bytes": int(cfg.get("max_image_bytes", MAX_JPEG_BYTES)),
    }


def get_api_key():
    """Key from environment only. Empty string = disabled."""
    return (os.environ.get("XKIRO_API_KEY") or "").strip()


def build_chat_payload(model, event_type, severity, data_url):
    """OpenAI-compatible vision payload builder (pure function, testable offline)."""
    prompt = (
        "You are a jail-cell incident verifier. Local detector reports: "
        f"{event_type} severity={severity}. "
        "Reply in strict JSON: {\"verdict\": \"confirm\"|\"reject\"|\"unsure\", "
        "\"reason\": str, \"caption\": str}. "
        "Reject only if clearly no person/contraband/fight visible."
    )
    return {
        "model": model,
        "max_tokens": 200,
        "temperature": 0.1,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
    }


def encode_frame_to_data_url(frame, max_bytes=MAX_JPEG_BYTES):
    """Encode BGR ndarray to JPEG data URL. Returns '' on failure."""
    try:
        import cv2
        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        if not ok:
            return ""
        raw = buf.tobytes()
        if len(raw) > max_bytes:
            # Re-encode smaller to bound cost
            import numpy as np
            h, w = frame.shape[:2]
            scale = 0.7
            small = cv2.resize(frame, (int(w * scale), int(h * scale)))
            ok2, buf2 = cv2.imencode(".jpg", small, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
            if ok2:
                raw = buf2.tobytes()
        b64 = base64.b64encode(raw).decode("ascii")
        return "data:image/jpeg;base64," + b64
    except Exception:
        return ""


class CloudVerifier:
    """Thread-safe, rate-limited async verifier. Singleton via get_cloud_verifier()."""

    def __init__(self):
        self.lock = threading.Lock()
        self.last_call_ts = 0.0

    def _can_call(self, cfg):
        if not cfg["enabled"]:
            return False
        if not get_api_key():
            return False
        if not _is_allowed_https_url(cfg["base_url"]):
            return False
        now = time.time()
        with self.lock:
            if now - self.last_call_ts < cfg["min_interval_s"]:
                return False
        return True

    def _mark_called(self):
        with self.lock:
            self.last_call_ts = time.time()

    def _post_blocking(self, cfg, payload):
        url = cfg["base_url"].rstrip("/") + "/chat/completions"
        if not _is_allowed_https_url(url):
            return {"verdict": "unsure", "reason": "blocked non-https url", "caption": ""}
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + get_api_key(),
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=cfg["timeout_s"]) as resp:
                raw = resp.read(64_000).decode("utf-8", errors="replace")
            data = json.loads(raw)
            text = ""
            try:
                text = data["choices"][0]["message"]["content"]
            except Exception:
                text = raw[:1000]
            return self._parse_model_text(text)
        except urllib.error.HTTPError as e:
            # 429 / 401 / 5xx -> fallback, never raise into alert path
            return {"verdict": "unsure", "reason": f"http {e.code}", "caption": ""}
        except Exception as e:
            return {"verdict": "unsure", "reason": f"net {type(e).__name__}", "caption": ""}

    @staticmethod
    def _parse_model_text(text):
        try:
            # Model instructed to reply strict JSON; tolerate fences
            t = text.strip()
            if t.startswith("```"):
                t = t.strip("`")
                # drop leading 'json' marker if present
                if t.lower().startswith("json"):
                    t = t[4:]
            obj = json.loads(t)
            v = str(obj.get("verdict", "unsure")).lower()
            if v not in ("confirm", "reject", "unsure"):
                v = "unsure"
            return {
                "verdict": v,
                "reason": str(obj.get("reason", ""))[:500],
                "caption": str(obj.get("caption", ""))[:500],
            }
        except Exception:
            return {"verdict": "unsure", "reason": "unparseable", "caption": text[:500]}

    def verify_async(self, camera_id, incident_id, event_type, severity, frame, callback=None):
        """Fire-and-forget enrichment. Never blocks. No-op when disabled/unconfigured."""
        cfg = get_cloud_verifier_config()
        if not self._can_call(cfg):
            return False
        data_url = encode_frame_to_data_url(frame, cfg["max_image_bytes"])
        if not data_url:
            return False
        payload = build_chat_payload(cfg["model"], event_type, severity, data_url)

        def _worker():
            result = self._post_blocking(cfg, payload)
            self._mark_called()
            try:
                from monitor_app.events import get_event_bus
                get_event_bus().publish(
                    "CLOUD_VERDICT",
                    camera_id=camera_id,
                    incident_id=incident_id,
                    event_type=event_type,
                    severity=severity,
                    verdict=result.get("verdict", "unsure"),
                    reason=result.get("reason", ""),
                    caption=result.get("caption", ""),
                )
            except Exception:
                pass
            if callback:
                try:
                    callback(result)
                except Exception:
                    pass

        self._mark_called()  # reserve slot at dispatch to enforce min_interval
        threading.Thread(target=_worker, daemon=True).start()
        return True


_global_cloud_verifier = CloudVerifier()


def get_cloud_verifier():
    return _global_cloud_verifier
