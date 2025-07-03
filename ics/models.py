from pydantic import BaseModel
from typing import List, Optional

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


class GroupSpec(BaseModel):
    name: str
    systemList: List[str] = []
    enabled: bool = False
    autoStart: bool = False
    ignoreDisabled: bool = True
    parallel: bool = False



