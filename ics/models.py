from pydantic import BaseModel, field_validator
from typing import List, Dict, Optional
from enum import Enum


# ----- Common / enums -----

class ResourceDesiredState(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"


class GroupDesiredState(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"


class GroupStateAction(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    CLEAR = "clear"
    FLUSH = "flush"


class ResourceStateAction(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    CLEAR = "clear"
    PROBE = "probe"


# ----- Node models -----

class NodeSpec(BaseModel):
    """
    Represents a node in a raft cluster.

    Attributes:
        hostname (str): The hostname or IP of the node.
        port (int): The port number of the node.
    """
    hostname: str
    port: int

    # Make the model immutable and hashable
    model_config = {"frozen": True}

    @property
    def node_id(self) -> str:
        return f"{self.hostname}:{self.port}"

    @classmethod
    def from_string(cls, node_id: str) -> "NodeSpec":
        """Create a Node instance from a node_id (e.g. 'hostname:port')."""
        hostname, port = node_id.split(":")
        return cls(hostname=hostname, port=int(port))

    @field_validator("port")
    def validate_port(cls, value: int):
        if not (1 <= value <= 65535):
            raise ValueError(f"Port must be between 1 and 65535, got {value}")
        return value

    def __str__(self):
        return self.node_id

    def __repr__(self):
        return f"Node(hostname={self.hostname}, port={self.port})"


# ----- Group models -----

class GroupAttributes(BaseModel):
    enabled: bool = False
    autoStart: bool = False
    ignoreDisabled: bool = True
    parallel: bool = False


class GroupSpec(BaseModel):
    name: str
    systemList: List[str] = []
    attributes: GroupAttributes = GroupAttributes()


# ----- Resource models -----

class ResourceAttributes(BaseModel):
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


class ResourceSpec(BaseModel):
    name: str
    group: str
    attributes: ResourceAttributes = ResourceAttributes()
    dependsOn: Optional[List[str]] = []


# ----- Raft RPCs -----

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


# ----- API -----

class ResourceStateUpdate(BaseModel):
    state: ResourceDesiredState
    node: Optional[str] = ""


class GroupStateUpdate(BaseModel):
    action: GroupStateAction
    node: Optional[str] = ""
