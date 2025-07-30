from pydantic import BaseModel
from typing import List, Dict, Optional
from enum import Enum

class ResourceState(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"

class ResourceSpec(BaseModel):
    name: str
    group: str

    enabled: bool = False
    startProgram: Optional[str] = ""
    stopProgram: Optional[str] = ""
    monitorProgram: Optional[str] = ""
    faultPropagation: bool = False
    onlineRetryLimit: int = 0
    restartLimit: int = 3
    monitorOnly: bool = False
    monitorInterval: int = 60
    offlineMonitorInterval: int = 180
    onlineTimeout: int = 60
    offlineTimeout: int = 60
    monitorTimeout: int = 60
    load: int = 1

    dependsOn: Optional[List[str]] = []

    desired_state: ResourceState = ResourceState.OFFLINE

class GroupSpec(BaseModel):
    name: str
    systemList: List[str] = []
    enabled: bool = False
    autoStart: bool = False
    ignoreDisabled: bool = True
    parallel: bool = False


class RequestVoteRequest(BaseModel):
    term: int
    candidate_id: str
    last_log_index: int
    last_log_term: int


class AppendEntriesRequest(BaseModel):
    term: int
    leader_id: str
    prev_log_index: int
    prev_log_term: int
    entries: List[Dict]
    leader_commit: int
