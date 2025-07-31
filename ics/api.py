from fastapi import FastAPI, HTTPException, Request

from ics.models import ResourceSpec, GroupSpec, RequestVoteRequest, AppendEntriesRequest
from ics.cluster_config import ClusterConfig


def create_api(raft_node):

    app = FastAPI(title="ICS API", version="3.0.0")

    def mutate_config(mutator):
        config = raft_node.get_latest_config()
        mutator(config)
        raft_node.propose_new_config(config)

    @app.get("/ping")
    async def ping():
        return {"status": "ok"}

    # -------- Raft --------

    @app.get("/raft/status")
    async def raft_status():
        if not raft_node:
            raise HTTPException(status_code=503, detail="Raft node unavailable")

        return raft_node.get_status()

    @app.get("/raft/config")
    async def raft_config():
        return raft_node.get_latest_config()

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

    @app.post("/raft/append_log")
    async def append_log(request: Request):
        data = await request.json()
        try:
            raft_node.append_entry(data)
            return {"status": "entry appended"}
        except RuntimeError as e:
            raise HTTPException(status_code=400, detail=str(e))

    # -------- Resources --------

    @app.get("/resources")
    async def list_resources():
        config = raft_node.get_latest_config()
        return {"resources": list(config.resources.keys())}

    @app.post("/resources")
    async def add_resource(resource: ResourceSpec):
        def mutator(config: ClusterConfig):
            config.add_resource(resource)
        mutate_config(mutator)
        return {"status": "added", "name": resource.name}

    @app.delete("/resources/{name}")
    async def delete_resource(name: str):
        def mutator(config: ClusterConfig):
            config.delete_resource(name)
        mutate_config(mutator)
        return {"status": "deleted", "name": name}

    @app.post("/resources/{name}/online")
    async def res_online(name: str):
        def mutator(config: ClusterConfig):
            config.res_online(name)
        mutate_config(mutator)
        return {"status": "resource set to online"}

    @app.post("/resources/{name}/offline")
    async def res_offline(name: str):
        def mutator(config: ClusterConfig):
            config.res_offline(name)
        mutate_config(mutator)
        return {"status": "resource set to offline"}

    # -------- Groups --------

    @app.get("/groups")
    async def list_groups():
        config = raft_node.get_latest_config()
        return {"groups": list(config.groups.keys())}

    @app.post("/groups")
    async def add_group(group: GroupSpec):
        def mutator(config: ClusterConfig):
            config.add_group(group)
        mutate_config(mutator)
        return {"status": "added", "name": group.name}

    @app.delete("/groups/{name}")
    async def delete_group(name: str):
        def mutator(config: ClusterConfig):
            config.delete_group(name)
        mutate_config(mutator)
        return {"status": "deleted", "name": name}

    @app.post("/groups/{name}/online")
    async def grp_online(name: str):
        def mutator(config: ClusterConfig):
            config.grp_online(name)
        mutate_config(mutator)
        return {"status": "group set to online"}

    @app.post("/groups/{name}/offline")
    async def grp_offline(name: str):
        def mutator(config: ClusterConfig):
            config.grp_offline(name)
        mutate_config(mutator)
        return {"status": "group set to offline"}

    return app
