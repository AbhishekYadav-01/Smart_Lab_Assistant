# data_models.py
from dataclasses import dataclass
from datetime import datetime

@dataclass
class Commitment:
    """Represents a commitment between agents"""
    debtor: str
    creditor: str
    time_adjustment: int
    future_obligation: str
    created_at: datetime
    episode: str
    status: str = "pending"

@dataclass
class Booking:
    """Represents a single booking in a lab's schedule."""
    booked_by: str
    start_time: datetime
    end_time: datetime
    student_count: int = 1
    flexibility_minutes: int = 0