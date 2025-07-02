from fastapi import FastAPI, HTTPException
from ics.models_specs import ResourceSpec, GroupSpec


def create_api(system):

    app = FastAPI(title="ICS API", version="3.0.0")

    @app.get("/ping")
    async def ping():
        return {"status": "ok"}

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
            "SystemList": ','.join(group.systemList),
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