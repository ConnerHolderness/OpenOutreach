from enum import Enum


class MessageStatus(Enum):
    SENT = "sent"
    SKIPPED = "skipped"


class ProfileState(str, Enum):
    DISCOVERED = "discovered"
    ENRICHED = "enriched"
    PENDING = "pending"
    CONNECTED = "connected"
    COMPLETED = "completed"
    FAILED = "failed"
    INACTIVE = "inactive"  # Skipped due to no recent activity
