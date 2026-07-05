import threading
import queue
import time
from typing import Dict, List, Optional
from monitor_app.logger import get_module_logger
from monitor_app.events import get_event_bus

logger = get_module_logger("TelemetryEngine")

class TelemetryEngine:
    """
    Asynchronous Telemetry Engine.
    Listens to the EventBus and queues metrics processing on a background thread.
    Enforces a strict DROP_OLDEST policy under queue overload to prevent pipeline blocking.
    """
    def __init__(self, max_queue_size: int = 2000):
        self.queue = queue.Queue(maxsize=max_queue_size)
        self.running = False
        self.worker_thread: Optional[threading.Thread] = None
        self.lock = threading.Lock()
        self.collectors = []
        self.event_drop_count = 0
        
        # Thread-safe Active Contexts registry
        self.active_contexts = {}
        self.active_contexts_lock = threading.Lock()

    def register_context(self, ctx):
        """Register a context so it can be referenced across threads via Frame UUID."""
        with self.active_contexts_lock:
            self.active_contexts[ctx.frame_uuid] = ctx

    def get_context(self, frame_uuid: str):
        """Get registered context by Frame UUID."""
        with self.active_contexts_lock:
            return self.active_contexts.get(frame_uuid)

    def retire_context(self, frame_uuid: str):
        """Pop and return a context by Frame UUID to prevent memory accumulation."""
        with self.active_contexts_lock:
            return self.active_contexts.pop(frame_uuid, None)

    def register_collector(self, collector):
        """Register a sub-collector instance."""
        with self.lock:
            if collector not in self.collectors:
                self.collectors.append(collector)

    def start(self):
        """Start the background worker thread and register EventBus subscriptions."""
        with self.lock:
            if self.running:
                return
            self.running = True
            
            # Start worker thread
            self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True, name="TelemetryWorker")
            self.worker_thread.start()
            
            # Subscribe to all telemetry events
            bus = get_event_bus()
            bus.subscribe("TELEM_FRAME_READ", self._enqueue_event)
            bus.subscribe("TELEM_PIPELINE_COMPLETE", self._enqueue_event)
            bus.subscribe("TELEM_FRAME_DROPPED", self._enqueue_event)
            bus.subscribe("TELEM_QUEUE_TICK", self._enqueue_event)
            bus.subscribe("TELEM_SYSTEM_TICK", self._enqueue_event)
            bus.subscribe("TELEM_HEALTH_ALERT", self._enqueue_event)
            bus.subscribe("TELEM_BENCHMARK_STATE", self._enqueue_event)
            
            logger.info("Telemetry Engine started successfully.")

    def stop(self):
        """Stop worker thread and clear queue."""
        with self.lock:
            if not self.running:
                return
            self.running = False
            
        if self.worker_thread:
            # Wake up thread from blocking get
            try:
                self.queue.put_nowait((None, None))
            except queue.Full:
                pass
            self.worker_thread.join(timeout=1.0)
            self.worker_thread = None
        
        logger.info("Telemetry Engine stopped.")

    def _enqueue_event(self, event_name: str, payload: dict):
        """Callback to safely enqueue EventBus triggers."""
        try:
            self.queue.put_nowait((event_name, payload))
        except queue.Full:
            # Enforce DROP_OLDEST policy
            try:
                # Discard oldest
                self.queue.get_nowait()
                with self.lock:
                    self.event_drop_count += 1
                # Put the new event
                self.queue.put_nowait((event_name, payload))
            except (queue.Empty, queue.Full):
                pass

    def _worker_loop(self):
        """Process queued telemetry events asynchronously."""
        while self.running:
            try:
                event_name, payload = self.queue.get(timeout=0.2)
                if event_name is None:  # Stop signal
                    break
                
                # Dispatch event to all registered collectors
                with self.lock:
                    active_collectors = list(self.collectors)
                
                for collector in active_collectors:
                    try:
                        collector.on_event(event_name, payload)
                    except Exception as ex:
                        # Log error internally without throwing
                        logger.error(f"Collector {collector.__class__.__name__} failed: {ex}")
                        
                self.queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Error in Telemetry Engine worker: {e}")

# Global singleton
_global_engine = TelemetryEngine()

def get_telemetry_engine() -> TelemetryEngine:
    return _global_engine
