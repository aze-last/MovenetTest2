import logging
from datetime import datetime

class StructuredFormatter(logging.Formatter):
    """
    Format: [Timestamp] [Level] [Category] [Component] [Message] [Reference ID]
    """
    def format(self, record):
        timestamp = datetime.fromtimestamp(record.created).strftime("%H:%M:%S.%f")[:-3]
        level = record.levelname
        
        # We expect record.msg to be a dict or we pass these via 'extra'
        category = getattr(record, 'category', 'SYSTEM')
        component = getattr(record, 'component', 'Unknown')
        reference_id = getattr(record, 'reference_id', '')
        
        ref_str = f" [Ref: {reference_id}]" if reference_id else ""
        
        msg = record.getMessage()
        
        return f"[{timestamp}] [{level}] [{category}] [{component}] {msg}{ref_str}"
