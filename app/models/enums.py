from enum import Enum

class JobCategory(str, Enum):
    TECH = "tech"
    MANAGEMENT = "management"
    DESIGN = "design"
    GENERAL = "general"

class UserRole(str, Enum):
    HR = "hr"
    MANAGER = "manager"
    ADMIN = "admin"

class EventType(str, Enum):
    SCREEN_START = "screen_start"
    SCREEN_END = "screen_end"
    FEEDBACK = "feedback"
    INTERVIEW_SEND = "interview_send"
    SESSION_SNAPSHOT = "session_snapshot"
    JOB_CLOSE = "job_close"

class FeedbackType(str, Enum):
    SUITABLE = "suitable"
    NOT_SUITABLE = "not_suitable"
    PENDING = "pending"