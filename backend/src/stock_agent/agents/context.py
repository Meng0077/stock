from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ResearchContext:
    as_of: datetime
