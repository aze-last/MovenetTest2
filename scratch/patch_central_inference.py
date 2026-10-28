with open('monitor_app/central_inference.py', 'r', encoding='utf-8') as f:
    text = f.read()

target = """        # Stop performance monitor
        from monitor_app.monitor_logging import get_performance_monitor
        get_performance_monitor().stop()
        logger.info("Queue Worker stopped.")"""

repl = """        # Drain any leftover tasks
        while not self.task_queue.empty():
            try:
                self.task_queue.get_nowait()
            except queue.Empty:
                break

        # Stop performance monitor
        from monitor_app.monitor_logging import get_performance_monitor
        get_performance_monitor().stop()
        logger.info("Queue Worker stopped.")"""

assert target in text, "target not found in central_inference.py"
text = text.replace(target, repl, 1)

with open('monitor_app/central_inference.py', 'w', encoding='utf-8', newline='') as f:
    f.write(text)

print("SUCCESS: central_inference.py patched")

