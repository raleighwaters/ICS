import logging

from fastapi import FastAPI, HTTPException, Request

import ics.errors
from ics.models import ResourceSpec, GroupSpec, RequestVoteRequest, AppendEntriesRequest
from ics.cluster_config import ClusterConfig
from ics.cluster_actions import cluster_resource_states, cluster_resource_probe, cluster_resource_state, cluster_resource_clear


logger = logging.getLogger(__name__)

def check_resource(name, system):
    try:
        system.get_resource(name)
    except ics.errors.ICSError:
        logger.error(f"Resource {name} not found in system")
        raise HTTPException(status_code=404, detail=f"Resource {name} not found")

def check_group(name, system):
    try:
        system.get_group(name)
    except ics.errors.ICSError:
        raise HTTPException(status_code=404, detail=f"Group {name} not found")


def create_api(raft_node, system):

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

    @app.get("/raft/log")
    async def raft_log():
        return raft_node.log

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

    @app.get("/resources/{name}")
    async def get_resource(name: str):
        check_resource(name, system)
        config = raft_node.get_latest_config()
        data = config.resource(name)
        return {"data": data}

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

    @app.get("/resources/{name}/state")
    async def res_state(name: str):
        check_resource(name, system)
        return await cluster_resource_state(raft_node, system, name)

    @app.get("/resources/{name}/dependency")
    async def res_dependency(name: str):
        check_resource(name, system)
        config = raft_node.get_latest_config()
        dependencies = config.res_dependency(name)
        return {"data": dependencies}

    @app.put("/resources/{name}/dependency/{dep_name}")
    async def add_resource_dependency(name: str, dep_name: str):
        check_resource(name, system)
        check_resource(dep_name, system)

        def mutator(config: ClusterConfig):
            try:
                config.link_dependency(name, dep_name)
            except ValueError as err:
                raise HTTPException(status_code=400, detail=f"{err}")

        mutate_config(mutator)
        return {"status": "added", "resource": name, "dependency": dep_name}

    @app.delete("/resources/{name}/dependency/{dep_name}")
    async def remove_resource_dependency(name: str, dep_name: str):
        check_resource(name, system)

        def mutator(config: ClusterConfig):
            try:
                config.unlink_dependency(name, dep_name)
            except ValueError as err:
                raise HTTPException(status_code=400, detail=f"{err}")

        mutate_config(mutator)
        return {"status": "removed", "resource": name, "dependency": dep_name}

    @app.get("/resources/{name}/clear")
    async def resource_clear(name: str):
        check_resource(name, system)
        return await cluster_resource_clear(raft_node, system, name)

    @app.get("/resources/{name}/probe")
    async def resource_probe(name: str):
        check_resource(name, system)
        return await cluster_resource_probe(raft_node, system, name)

    @app.patch("/resources/{name}/attributes")
    async def modify_resources_attributes(name: str, updates: dict):
        check_resource(name, system)

        def mutator(config: ClusterConfig):
            try:
                config.res_attr_update(name, updates)
            except ValueError as err:
                raise HTTPException(status_code=400, detail=str(err))

        mutate_config(mutator)
        return {"status": "updated"}

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

    # -------- State --------

    @app.get("/state/nodes")
    async def state_notes():
        pass

    @app.get("/state/groups")
    async def state_groups():
        pass

    @app.get("/state/resources")
    async def state_resources():
        return await cluster_resource_states(raft_node, system)

    # -------- Local Resources --------

    @app.get("/local/resources/{name}/clear")
    async def local_resource_clear(name: str):
        check_resource(name, system)
        system.res_clear(name)
        return {"status": "success"}


    @app.get("/local/resources/{name}/probe")
    async def local_resource_probe(name: str):
        check_resource(name, system)
        system.res_state(name)
        return {"status": "success"}

    # -------- Local Groups --------

    # -------- Local States --------

    @app.get("/local/state/groups")
    async def state_groups_local():
        pass

    @app.get("/local/state/resources")
    async def state_resources_local():
        config = raft_node.get_latest_config()
        resources = config.resource_names()
        return {
            "data": { name: system.res_state(name) for name in resources }
        }

    return app
