from fastapi import FastAPI, HTTPException
from ics.models_specs import ResourceSpec, GroupSpec


# In-memory stores (you'll replace these with your engine later)
resources = {}
groups = {}


def create_api(system):

    app = FastAPI(title="ICS API", version="3.0.0")

    @app.get("/ping")
    async def ping():
        return {"status": "ok"}

    # -------- Resources --------

    @app.get("/resources")
    async def list_resources():
        return list(resources.keys())

    @app.post("/resources")
    async def add_resources(resource: ResourceSpec):
        if resource.name in resources:
            raise HTTPException(status_code=400, detail="Resource already exists")
        resources[resource.name] = resource
        return {"status": "added", "name": resource.name}

    @app.get("/resources/{name}")
    async def get_resource(name: str):
        if name not in resources:
            raise HTTPException(status_code=404, detail="Resource not found")
        return resources[name]

    @app.delete("/resources/{name}")
    async def delete_resource(name: str):
        if name not in resources:
            raise HTTPException(status_code=404, detail="Resource not found")
        del resources[name]
        return {"status": "deleted", "name": name}

    # -------- Groups --------

    @app.get("/groups")
    async def list_groups():
        return list(groups.keys())

    @app.post("/groups")
    async def add_group(group: GroupSpec):
        if group.name in groups:
            raise HTTPException(status_code=400, detail="Group already exists")
        groups[group.name] = group
        return {"status": "added", "name": group.name}

    @app.get("/groups/{name}")
    async def get_group(name: str):
        if name not in groups:
            raise HTTPException(status_code=404, detail="Group not found")
        return groups[name]

    @app.delete("/groups/{name}")
    async def delete_group(name: str):
        if name not in groups:
            raise HTTPException(status_code=404, detail="Group not found")
        del groups[name]
        return {"status": "deleted", "name": name}

    return app