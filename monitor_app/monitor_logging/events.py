from monitor_app.monitor_logging.logger import get_module_logger

logger = get_module_logger("Events")

class SystemEvents:
    @staticmethod
    def camera_connected(camera_id: str, name: str):
        logger.info(f"Camera CONNECTED | Name: {name}", camera_id=camera_id)

    @staticmethod
    def camera_disconnected(camera_id: str, name: str, reason: str = ""):
        logger.warning(f"Camera DISCONNECTED | Name: {name} | Reason: {reason}", camera_id=camera_id)

    @staticmethod
    def camera_reconnecting(camera_id: str, attempt: int):
        logger.info(f"Camera RECONNECTING | Attempt: {attempt}", camera_id=camera_id)

    @staticmethod
    def camera_recovered(camera_id: str):
        logger.info(f"Camera RECOVERED", camera_id=camera_id)

    @staticmethod
    def motion_gate_enabled(camera_id: str):
        logger.info("Motion Gate ENABLED", camera_id=camera_id)

    @staticmethod
    def motion_gate_disabled(camera_id: str):
        logger.info("Motion Gate DISABLED", camera_id=camera_id)

    @staticmethod
    def heavy_ai_enabled(camera_id: str):
        logger.info("Heavy AI ENABLED", camera_id=camera_id)

    @staticmethod
    def heavy_ai_disabled(camera_id: str):
        logger.info("Heavy AI DISABLED", camera_id=camera_id)

    @staticmethod
    def stable_id_created(camera_id: str, stable_id: int):
        logger.info(f"StableID {stable_id} CREATED", camera_id=camera_id)

    @staticmethod
    def stable_id_lost(camera_id: str, stable_id: int):
        logger.info(f"StableID {stable_id} LOST", camera_id=camera_id)

    @staticmethod
    def stable_id_merged(camera_id: str, src_id: int, dest_id: int):
        logger.info(f"StableID {src_id} MERGED into {dest_id}", camera_id=camera_id)

    @staticmethod
    def behavior_detected(camera_id: str, stable_id: int, behavior_type: str, details: str):
        logger.info(f"Behavior Detected | Person {stable_id} | Type: {behavior_type} | Details: {details}", camera_id=camera_id)

    @staticmethod
    def behavior_rejected(camera_id: str, stable_id: int, behavior_type: str, reason: str):
        logger.debug(f"Behavior Rejected | Person {stable_id} | Type: {behavior_type} | Reason: {reason}", camera_id=camera_id)

    @staticmethod
    def incident_started(camera_id: str, incident_id: str, event_type: str):
        logger.info(f"Incident Started | Incident ID: {incident_id} | Type: {event_type}", camera_id=camera_id, incident_id=incident_id)

    @staticmethod
    def incident_extended(camera_id: str, incident_id: str, event_type: str):
        logger.info(f"Incident Extended | Incident ID: {incident_id} | Type: {event_type}", camera_id=camera_id, incident_id=incident_id)

    @staticmethod
    def incident_closed(camera_id: str, incident_id: str, duration: float, evidence_count: int):
        logger.info(f"Incident Closed | Incident ID: {incident_id} | Duration: {duration:.2f}s | Evidence Count: {evidence_count}", camera_id=camera_id, incident_id=incident_id)

    @staticmethod
    def recorder_started(camera_id: str, incident_id: str, video_path: str):
        logger.info(f"Recorder Started | Video: {video_path}", camera_id=camera_id, incident_id=incident_id)

    @staticmethod
    def prebuffer_attached(camera_id: str, incident_id: str, frame_count: int):
        logger.info(f"Prebuffer Attached | Frame Count: {frame_count}", camera_id=camera_id, incident_id=incident_id)

    @staticmethod
    def recorder_stopped(camera_id: str, incident_id: str, video_path: str):
        logger.info(f"Recorder Stopped | Saved: {video_path}", camera_id=camera_id, incident_id=incident_id)

    @staticmethod
    def health_warning(component: str, message: str):
        logger.warning(f"Health Warning | Component: {component} | Msg: {message}")

    @staticmethod
    def queue_overflow(camera_id: str, queue_size: int):
        logger.warning(f"Queue Overflow (Backpressure) | Queue Size: {queue_size}", camera_id=camera_id)

    @staticmethod
    def inference_timeout(camera_id: str, duration: float):
        logger.warning(f"Inference Timeout | Duration: {duration:.2f}s", camera_id=camera_id)

    @staticmethod
    def critical_error(component: str, message: str):
        logger.critical(f"Critical Failure | Component: {component} | Msg: {message}")
