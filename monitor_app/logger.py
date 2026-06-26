# Forward all calls to monitor_app.monitor_logging.logger to prevent breaking imports
from monitor_app.monitor_logging.logger import get_logger, get_module_logger, ComponentLogger, setup_logging
