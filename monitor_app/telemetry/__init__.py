from monitor_app.telemetry.context import TelemetryContext
from monitor_app.telemetry.engine import get_telemetry_engine

# Import and instantiate collectors
from monitor_app.telemetry.collectors.camera import CameraCollector
from monitor_app.telemetry.collectors.ai import AICollector
from monitor_app.telemetry.collectors.system import SystemCollector
from monitor_app.telemetry.collectors.queue import QueueCollector
from monitor_app.telemetry.collectors.health import HealthCollector

engine = get_telemetry_engine()

camera_collector = CameraCollector()
ai_collector = AICollector()
system_collector = SystemCollector()
queue_collector = QueueCollector()
health_collector = HealthCollector()

engine.register_collector(camera_collector)
engine.register_collector(ai_collector)
engine.register_collector(system_collector)
engine.register_collector(queue_collector)
engine.register_collector(health_collector)
