import asyncio
import logging
from typing import List

import httpx

from ics.raft_node import Node
from ics.models import ResourceDesiredState, GroupDesiredState, GroupAttributes, GroupStateAction


logger = logging.getLogger(__name__)


async def fan_out_api_call(path: str, nodes: List[Node], method="GET", payload=None):
    result = {}

    async with httpx.AsyncClient(timeout=2) as client:
        tasks = []
        for node in nodes:
            url = f"http://{node}/{path}"
            if method == "GET":
                tasks.append(client.get(url))
            elif method == "PUT":
                tasks.append(client.put(url, json=payload))
            else:
                logger.error(f"Unsupported method for fan out API call: {method}")
                continue

        responses = await asyncio.gather(*tasks, return_exceptions=True)

        for node, response in zip(nodes, responses):
            if isinstance(response, Exception):
                logger.error(f"{node.node_id} failed: {response}")
                result[node.hostname] = {"status": "failed", "error": str(response)}
                continue

            try:
                data = response.json()
                result[node.hostname] = data.get("data", {"status": "unknown"})
            except (KeyError, AttributeError):
                result[node.hostname] = {"status": "failed", "error": f"Bad JSON response: {data}"}

    return result


async def cluster_group_states(raft_node, system):
    local_node = raft_node.local_node
    peers = raft_node.peers

    results = {
        "data": { name: {local_node.hostname: state} for name, state in system.grp_state_many() }
    }

    remote_results = await fan_out_api_call(f"local/state/groups", peers)
    for node, result in remote_results.items():
        if result.get("status") == "failed":
            logger.error(f"Error retrieving state from {node}: {result.get('error')}")
            for group_name in results["data"]:
                results["data"][group_name][node] = "ERROR"
        for name, state in result.items():
            results["data"].setdefault(name, {})[node] = state

    return results


async def cluster_group_state_change(raft_node, system, name, state: GroupDesiredState, node_name=None):
    local_node = raft_node.local_node

    results = {"data": {}}

    # Determine node list
    if node_name:
        try:
            nodes = [raft_node.get_node(node_name)]
        except ValueError as err:
            return {"status": "failed", "error": str(err)}
    elif state == GroupDesiredState.ONLINE:
        nodes = raft_node.nodes() #TODO: THis should be an algorithm to determine node list
    elif state == GroupDesiredState.OFFLINE:
        nodes = raft_node.nodes()

    # Run local node if in list
    if local_node in nodes:
        if state == GroupDesiredState.ONLINE:
            system.grp_online(name)
        elif state ==  GroupDesiredState.OFFLINE:
            system.grp_offline(name)

        results["data"][local_node.hostname] = {"status": "success"}

        nodes.remove(local_node)

    # If no nodes are left, report as completed
    if not nodes:
        return results

    # Create API call payload
    action_map = {
        GroupDesiredState.ONLINE: "online",
        GroupDesiredState.OFFLINE: "offline",
    }
    payload = {"action": action_map.get(state)}

    # Execute fan out API call

    remote_results = await fan_out_api_call(f"local/groups/{name}/state", nodes, method="PUT", payload=payload)
    results["data"].update(remote_results)
    return results


async def cluster_group_action(raft_node, system, name, node_name, action: GroupStateAction):
    local_node = raft_node.local_node

    if node_name == local_node.hostname:
        try:
            if action == GroupStateAction.CLEAR:
                system.grp_clear(name)
            elif action == GroupStateAction.FLUSH:
                system.grp_flush(name)
            return {"data": {"status": "success"}}
        except Exception as err:
            return {"data": {"status": "failed", "error": str(err)}}

    else:
        try:
            node = raft_node.get_node(node_name)
        except ValueError as err:
            return {"data": {"status": "failed", "error": str(err)}}

        remote_results = await fan_out_api_call(f"local/group/{name}/state", [node], method="PUT", payload={"action": action.value})
        return {"data": remote_results}


async def cluster_resource_state_change(raft_node, system, name, node_name, state: ResourceDesiredState):
    local_node = raft_node.local_node

    if node_name == local_node.hostname:
        if state == ResourceDesiredState.ONLINE:
            system.res_online(name)
            return {"status": "success"}
        elif state == ResourceDesiredState.OFFLINE:
            system.res_offline(name)
            return {"status": "success"}
    else:
        try:
            node = raft_node.get_node(node_name)
        except ValueError as err:
            return {"status": "failed", "error": str(err)}

        try:
            payload = {"state": state.value}
            async with httpx.AsyncClient(timeout=2) as client:
                response = await client.put(f"http://{node}/local/resources/{name}/state", json=payload)
                response.raise_for_status()
                return response.json()
        except ValueError as err:
            return {"status": "failed"}
        except httpx.RequestError as err:
            return {"status": "failed", "error": f"Failed to connect to node {node_name}: {str(err)}"}
        except httpx.HTTPStatusError as err:
            return {"status": "failed",
                    "error": f"HTTP error {err.response.status_code} on node {node_name}: {err.response.text}"}

async def cluster_resource_states(raft_node, system):
    local_node = raft_node.local_node
    peers = raft_node.peers

    results = {
        "data": { name: {local_node.hostname: state} for name, state in system.res_state_many() }
    }

    remote_results = await fan_out_api_call(f"local/state/resources", peers)
    for node, result in remote_results.items():
        if result.get("status") == "failed":
            logger.error(f"Error retrieving state from {node}: {result.get('error')}")
            for resource_name in results["data"]:
                results["data"][resource_name][node] = "ERROR"
        else:
            for name, state in result.items():
                results["data"].setdefault(name, {})[node] = state

    return results


async def cluster_resource_state(raft_node, system, name):
    local_node = raft_node.local_node
    peers = raft_node.peers

    local_state = system.res_state(name)
    result = {
        "data": {local_node.hostname: local_state}
    }

    remote_results = await fan_out_api_call(f"local/resources/{name}/state", peers)
    result["data"].update(remote_results)
    logger.info(f"Returning result: {result}")
    return result


async def cluster_resource_clear(raft_node, system, name):
    local_node = raft_node.local_node
    peers = raft_node.peers

    try:
        system.res_clear(name)
        local_status = {"status": "success"}
    except Exception as err:
        local_status = {"status": "failed", "error": str(err)}

    result = {
        "data": {name: {local_node.hostname: local_status}}
    }

    remote_results = await fan_out_api_call(f"local/resources/{name}/clear", peers)
    result["data"][name].update(remote_results)
    return result


async def cluster_resource_probe(raft_node, system, name):
    local_node = raft_node.local_node
    peers = raft_node.peers

    try:
        system.res_probe(name)
        local_status = {"status": "success"}
    except Exception as err:
        local_status = {"status": "failed", "error": str(err)}

    result = {
        "data": {name: {local_node.hostname: local_status}}
    }

    remote_results = await fan_out_api_call(f"local/resources/{name}/probe", peers)
    result["data"][name].update(remote_results)
    return result
