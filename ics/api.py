from fastapi import FastAPI, HTTPException
from ics.models import ResourceSpec, GroupSpec, RequestVoteRequest, AppendEntriesRequest


def create_api(system, raft_node):

    app = FastAPI(title="ICS API", version="3.0.0")

    @app.get("/ping")
    async def ping():
        return {"status": "ok"}

    # -------- Raft --------

    @app.get("/raft/status")
    async def raft_status():
        if not raft_node:
            raise HTTPException(status_code=503, detail="Raft node unavailable")

        with raft_node.lock:
            return {
                "node_id": raft_node.node_id,
                "term": raft_node.current_term,
                "role": raft_node.role.value,
                "voted_for": raft_node.voted_for,
                "log_length": len(raft_node.log),
                "commit_index": raft_node.commit_index,
                "last_applied": raft_node.last_applied
            }

    @app.post("/raft/request_vote")
    async def request_vote(data: RequestVoteRequest):
        if not raft_node:
            raise HTTPException(status_code=503, detail="Raft node unavailable")

        result = raft_node.handle_request_vote(
            term=data.term,
            candidate_id=data.candidate_id,
            last_log_index=data.last_log_index,
            last_log_term=data.last_log_term,
        )
        return result

    @app.post("/raft/append_entries")
    async def append_entries(data: AppendEntriesRequest):
        if not raft_node:
            raise HTTPException(status_code=503, detail="Raft node unavailable")

        result = raft_node.handle_append_entries(
            term=data.term,
            leader_id=data.leader_id,
            prev_log_index=data.prev_log_index,
            prev_log_term=data.prev_log_term,
            entries=data.entries,
            leader_commit=data.leader_commit
        )
        return result

    # -------- Resources --------

    @app.get("/resources")
    async def list_resources():
        return {"resources": system.res_list()}

    @app.post("/resources")
    async def add_resources(resource: ResourceSpec):
        if resource.name in system.res_list():
            raise HTTPException(status_code=400, detail="Resource already exists")

        system.res_add(resource.name, resource.group)

        attr_map = {
            "Enabled": str(resource.enabled).lower(),
            "StartProgram": resource.startProgram or "",
            "StopProgram": resource.stopProgram or "",
            "MonitorProgram": resource.monitorProgram or "",
            "FaultPropagation": str(resource.faultPropagation).lower(),
            "OnlineRetryLimit": str(resource.onlineRetryLimit),
            "RestartLimit": str(resource.restartLimit),
            "MonitorOnly": str(resource.monitorOnly).lower(),
            "MonitorInterval": str(resource.monitorInterval),
            "OfflineMonitorInterval": str(resource.offlineMonitorInterval),
            "OnlineTimeout": str(resource.onlineTimeout),
            "OfflineTimeout": str(resource.offlineTimeout),
            "MonitorTimeout": str(resource.monitorTimeout),
            "Load": str(resource.load),
        }

        for key, value in attr_map.items():
            system.res_modify(resource.name, key, value)

        # Add dependency links
        if resource.dependsOn:
            for parent in resource.dependsOn:
                if parent not in system.res_list():
                    raise HTTPException(
                        status_code=400,
                        detail=f"Dependency '{parent}' not found for resource '{resource.name}'"
                    )
                system.res_link(resource.name, parent)

        return {"status": "added", "name": resource.name}

    @app.get("/resources/{name}")
    async def get_resource(name: str):
        if name not in system.res_list():
            raise HTTPException(status_code=404, detail="Resource not found")

        resource = system.get_resource(name)
        return resource.to_spec()

    @app.delete("/resources/{name}")
    async def delete_resource(name: str):
        if name not in system.res_list():
            raise HTTPException(status_code=404, detail="Resource not found")

        system.res_delete(name)
        return {"status": "deleted", "name": name}

    # -------- Groups --------

    @app.get("/groups")
    async def list_groups():
        return {"groups": system.grp_list()}

    @app.post("/groups")
    async def add_group(group: GroupSpec):
        if group.name in system.grp_list():
            raise HTTPException(status_code=400, detail="Group already exists")

        system.grp_add(group.name)

        attr_map = {
            "Enabled": str(group.enabled).lower(),
            "AutoStart": str(group.autoStart).lower(),
            "IgnoreDisabled": str(group.ignoreDisabled).lower(),
            "Parallel": str(group.parallel).lower(),
            "SystemList": group.systemList,
        }

        for key, value in attr_map.items():
            system.grp_modify(group.name, key, value)

        return {"status": "added", "name": group.name}

    @app.get("/groups/{name}")
    async def get_group(name: str):
        if name not in system.grp_list():
            raise HTTPException(status_code=404, detail="Group not found")

        group = system.get_group(name)
        return group.to_spec()

    @app.delete("/groups/{name}")
    async def delete_group(name: str):
        if name not in system.grp_list():
            raise HTTPException(status_code=404, detail="Group not found")

        system.grp_delete(name)
        return {"status": "deleted", "name": name}

    return app
