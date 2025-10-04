from dataclasses import dataclass
from datetime import datetime

@dataclass
class Commitment:
    debtor: str
    creditor: str
    time_adjustment: int
    future_obligation: str
    created_at: datetime
    episode: str
    status: str = "pending"

@dataclass
class Booking:
    booked_by: str
    start_time: datetime
    end_time: datetime
    student_count: int = 1
    flexibility_minutes: int = 0
