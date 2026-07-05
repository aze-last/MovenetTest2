from typing import Dict, List, NamedTuple, Optional

class RegisteredMetric(NamedTuple):
    metric_id: str
    name: str
    unit: str
    group: str  # e.g., "system", "camera", "ai_pipeline", "health", "queue"

class TelemetryRegistry:
    """
    Central registry for decoupling metrics definition from visual dashboards,
    database schemas, and file exporters.
    """
    _instance: Optional['TelemetryRegistry'] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(TelemetryRegistry, cls).__new__(cls)
            cls._instance._metrics = {}
        return cls._instance

    def register_metric(self, metric_id: str, name: str, unit: str, group: str) -> None:
        """Registers a new metric in the registry."""
        self._metrics[metric_id] = RegisteredMetric(metric_id, name, unit, group)

    def get_metric(self, metric_id: str) -> Optional[RegisteredMetric]:
        """Retrieves a registered metric by ID."""
        return self._metrics.get(metric_id)

    def get_all_metrics(self) -> List[RegisteredMetric]:
        """Returns all registered metrics."""
        return list(self._metrics.values())

    def get_metrics_by_group(self, group: str) -> List[RegisteredMetric]:
        """Returns all registered metrics belonging to a specific group."""
        return [m for m in self._metrics.values() if m.group == group]

_global_registry = TelemetryRegistry()

def get_registry() -> TelemetryRegistry:
    return _global_registry
