import asyncio
import logging

import httpx
logger = logging.getLogger(__name__)


async def fan_out_api_call(path: str, raft_node):

    result = {}
    peer_ids = raft_node.peers

    async with httpx.AsyncClient(timeout=2) as client:
        tasks = []
        for peer_id in peer_ids:
            tasks.append(client.get(f"http://{peer_id}/{path}"))

        responses = await asyncio.gather(*tasks, return_exceptions=True)

        for peer_id, response in zip(peer_ids, responses):
            if isinstance(response, Exception):
                logger.error(f"{peer_id} failed: {response}")
                result[peer_id] = {"status": "failed", "error": str(response)}
                continue

            try:
                data = response.json()
                result["data"][peer_id] = data.get("data", {"status": "unknown"})
            except Exception as err:
                result[peer_id] = {"status": "failed", "error": "bad JSON"}

    return result


async def cluster_resource_states(raft_node, system):
    peer_ids = raft_node.peers
    node_id = raft_node.node_id

    result = {
        "data": {
            name: {node_id: state} for name, state in system.res_state_many()
        }
    }

    #TODO: Implement using common fan_out_api_call function
    async with httpx.AsyncClient(timeout=2) as client:
        tasks = []
        for peer_id in peer_ids:
            tasks.append(client.get(f"http://{peer_id}/local/state/resources"))

        responses = await asyncio.gather(*tasks, return_exceptions=True)

        for peer_id, response in zip(peer_ids, responses):
            if isinstance(response, Exception):
                logger.error(f"Failed to get state from {peer_id}")

                # Insert FAULT for each known resource
                for res_name in result.keys():
                    result["data"][res_name][peer_id] = "FAULT"
                continue
            try:
                node_data = response.json()
                for name, state in node_data["data"].items():
                    result["data"].setdefault(name, {})[peer_id] = state
            except Exception:
                logger.error(f"Failed to extract response from {peer_id}")
                continue

    return result


async def cluster_resource_state(raft_node, system, name):
    node_id = raft_node.node_id

    local_state = system.res_state(name)

    result = {
        "data": {node_id: local_state}
    }

    remote_results = await fan_out_api_call(f"/local/resources/{name}/state", raft_node)
    result["data"].update(remote_results)
    return result


async def cluster_resource_clear(raft_node, system, name):
    node_id = raft_node.node_id

    try:
        system.res_clear(name)
        local_status = {"status": "success"}
    except Exception as err:
        local_status = {"status": "failed", "error": str(err)}

    result = {
        "data": {name: {node_id: local_status}}
    }

    remote_results = await fan_out_api_call(f"/local/resources/{name}/clear", raft_node)
    result["data"][name].update(remote_results)
    return result


async def cluster_resource_probe(raft_node, system, name):
    node_id = raft_node.node_id

    try:
        system.res_probe(name)
        local_status = {"status": "success"}
    except Exception as err:
        local_status = {"status": "failed", "error": str(err)}

    result = {
        "data": {name: {node_id: local_status}}
    }

    remote_results = await fan_out_api_call(f"/local/resources/{name}/probe", raft_node)
    result["data"][name].update(remote_results)
    return result
