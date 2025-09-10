import logging

from fastapi import FastAPI, HTTPException, Request, Response
import httpx

import ics.errors
from ics.models import ResourceSpec, GroupSpec, RequestVoteRequest, AppendEntriesRequest, ResourceDesiredState, \
    GroupDesiredState, GroupStateUpdate, GroupStateAction
from ics.models import ResourceStateUpdate
from ics.raft_node import Node
from ics.cluster_config import ClusterConfig
from ics.cluster_actions import cluster_group_states, cluster_group_state_change, cluster_group_action

from ics.cluster_actions import cluster_resource_states, cluster_resource_probe, cluster_resource_state, cluster_resource_clear, cluster_resource_state_change

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

async def forward_request_to_leader(raft_node, request: Request):

    leader_node = raft_node.get_leader_node()
    if not leader_node:
        raise HTTPException(status_code=503, detail="Leader node unavailable")

    leader_url = f"http://{leader_node.hostname}:{leader_node.port}"

    # Construct the full URL to the leader
    url = f"{leader_url}{request.url.path}"
    if request.url.query:
        url += f"?{request.url.query}"

    try:
        async with httpx.AsyncClient() as client:
            # Forward method, headers, body
            resp = await client.request(
                method=request.method,
                url=url,
                headers=request.headers.raw,  # Pass raw headers
                content=await request.body()
            )

        # Return a FastAPI-compatible Response with status and content
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            headers=dict(resp.headers),
            media_type=resp.headers.get("content-type")
        )

    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"Leader unreachable: {e}")


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
            candidate_node=Node.from_string(data.candidate_id),
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

    # -------- Groups --------

    @app.get("/groups")
    async def list_groups():
        config = raft_node.get_latest_config()
        return {"data": {"groups": list(config.groups.keys())}}

    @app.post("/groups")
    async def add_group(request: Request, group: GroupSpec):
        if not raft_node.is_leader():
            return await forward_request_to_leader(raft_node, request)

        def mutator(config: ClusterConfig):
            config.add_group(group)
        mutate_config(mutator)
        return {"status": "added", "name": group.name}

    @app.get("/groups/{name}")
    async def get_group(name: str):
        check_group(name, system)
        config = raft_node.get_latest_config()
        data = config.group(name)
        return {"data": data}

    @app.delete("/groups/{name}")
    async def delete_group(request: Request, name: str):
        if not raft_node.is_leader():
            return await forward_request_to_leader(raft_node, request)

        def mutator(config: ClusterConfig):
            config.delete_group(name)
        mutate_config(mutator)
        return {"status": "deleted", "name": name}

    @app.put("/groups/{name}/state")
    async def change_group_state(name, state_update=GroupStateUpdate):
        check_group(name, system)
        action = state_update.action
        if action == GroupStateAction.ONLINE:
            return await cluster_group_state_change(raft_node, system, name, GroupDesiredState.ONLINE, node_name=state_update.node)
        elif action == GroupStateAction.OFFLINE:
            return await cluster_group_state_change(raft_node, system, name, GroupDesiredState.OFFLINE, node_name=state_update.node)
        elif action in [GroupStateAction.CLEAR, GroupStateAction.FLUSH]:
            return await cluster_group_action(raft_node, system, name, state_update.node, action)
        else:
            # This should never happen, but just in case
            raise HTTPException(status_code=400, detail=f"Unknown action {action}")

    @app.patch("/groups/{name}/attributes")
    async def modify_group_attributes(request: Request, name: str, updates: dict):
        if not raft_node.is_leader():
            return await forward_request_to_leader(raft_node, request)

        check_group(name, system)

        def mutator(config: ClusterConfig):
            try:
                config.grp_attr_update(name, updates)
            except ValueError as err:
                raise HTTPException(status_code=400, detail=str(err))

        mutate_config(mutator)
        return {"status": "updated"}

    # -------- Resources --------

    @app.get("/resources")
    async def list_resources():
        config = raft_node.get_latest_config()
        return {"resources": list(config.resources.keys())}

    @app.post("/resources")
    async def add_resource(request: Request, resource: ResourceSpec):
        if not raft_node.is_leader():
            return await forward_request_to_leader(raft_node, request)

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
    async def delete_resource(request: Request, name: str):
        if not raft_node.is_leader():
            return await forward_request_to_leader(raft_node, request)

        def mutator(config: ClusterConfig):
            config.delete_resource(name)
        mutate_config(mutator)
        return {"status": "deleted", "name": name}

    @app.get("/resources/{name}/state")
    async def res_state(name: str):
        check_resource(name, system)
        return await cluster_resource_state(raft_node, system, name)

    @app.put("/resources/{name}/state")
    async def change_resource_state(name: str, state_update: ResourceStateUpdate):
        check_resource(name, system)
        return await cluster_resource_state_change(raft_node, system, name, state_update.node, state_update.state)

    @app.get("/resources/{name}/dependency")
    async def res_dependency(name: str):
        check_resource(name, system)
        config = raft_node.get_latest_config()
        dependencies = config.res_dependency(name)
        return {"data": dependencies}

    @app.put("/resources/{name}/dependency/{dep_name}")
    async def add_resource_dependency(request: Request, name: str, dep_name: str):
        if not raft_node.is_leader():
            return await forward_request_to_leader(raft_node, request)

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
    async def remove_resource_dependency(request: Request, name: str, dep_name: str):
        if not raft_node.is_leader():
            return await forward_request_to_leader(raft_node, request)

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
    async def modify_resources_attributes(request: Request, name: str, updates: dict):
        if not raft_node.is_leader():
            return await forward_request_to_leader(raft_node, request)

        check_resource(name, system)

        def mutator(config: ClusterConfig):
            try:
                config.res_attr_update(name, updates)
            except ValueError as err:
                raise HTTPException(status_code=400, detail=str(err))

        mutate_config(mutator)
        return {"status": "updated"}

    # -------- State --------

    @app.get("/state/nodes")
    async def state_notes():
        pass

    @app.get("/state/groups")
    async def state_groups():
        return await cluster_group_states(raft_node, system)

    @app.get("/state/resources")
    async def state_resources():
        return await cluster_resource_states(raft_node, system)

    # -------- Local Resources --------

    @app.put("/local/resources/{name}/state")
    async def local_change_resource_state(name: str, state_update: ResourceStateUpdate):
        check_resource(name, system)
        if state_update.state == ResourceDesiredState.ONLINE:
            system.res_online(name)
        elif state_update.state == ResourceDesiredState.OFFLINE:
            system.res_offline(name)

        return {"status": "success"}

    @app.get("/local/resources/{name}/clear")
    async def local_resource_clear(name: str):
        check_resource(name, system)
        system.res_clear(name)
        return {"status": "success"}

    @app.get("/local/resources/{name}/probe")
    async def local_resource_probe(name: str):
        check_resource(name, system)
        system.res_probe(name)
        return {"status": "success"}

    # -------- Local Groups --------

    @app.put("/local/groups/{name}/state")
    async def local_change_group_state(name: str, state_update: GroupStateUpdate):
        check_group(name, system)
        action = state_update.action
        if action == GroupStateAction.ONLINE:
            system.grp_online(name)
        elif action == GroupStateAction.OFFLINE:
            system.grp_offline(name)
        elif action == GroupStateAction.CLEAR:
            system.grp_clear(name)
        elif action == GroupStateAction.FLUSH:
            system.grp_flush(name)
        else:
            # This should never happen, but just in case
            raise HTTPException(status_code=400, detail=f"{action}")
        return {"status": "success"}


    # -------- Local States --------

    @app.get("/local/state/groups")
    async def state_groups_local():
        config = raft_node.get_latest_config()
        groups = config.group_names()
        return {
            "data": { name: system.grp_state(name) for name in groups }
        }

    @app.get("/local/state/resources")
    async def state_resources_local():
        config = raft_node.get_latest_config()
        resources = config.resource_names()
        return {
            "data": { name: system.res_state(name) for name in resources }
        }

    return app
