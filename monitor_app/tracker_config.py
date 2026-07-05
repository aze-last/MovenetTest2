# ByteTrack algorithm configuration
# These are engineering algorithm parameters decoupled from UI and system config.

TRACKER_CFG = {
    "track_thresh": 0.2,     # High confidence threshold for tracking
    "track_buffer": 30,      # Frames to keep lost tracks
    "match_thresh": 0.8,     # Matching threshold for first stage
    "frame_rate": 15,        # Base frame rate for tracker
    "min_box_area": 10       # Minimum bounding box area
}
