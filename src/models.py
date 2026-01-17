# src/models.py
from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class DeprecationInfo:
    feature: str
    version_deprecated: str
    version_removed: Optional[str] = None
    module: Optional[str] = None
    description: str = ""
    replacement: Optional[str] = None
    url: Optional[str] = None

@dataclass
class JiraTicket:
    key: str
    summary: str
    status: str
    description: str
    assignee: Optional[str] = None

@dataclass
class BacklogTask:
    title: str
    description: str
    source_file: str
