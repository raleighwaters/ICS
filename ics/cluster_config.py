import logging
from pydantic import BaseModel, Field
from typing import Dict

from ics.models import GroupSpec, ResourceSpec
from ics.settings import settings

logger = logging.getLogger(__name__)

class ClusterConfig(BaseModel):
    groups: Dict[str, GroupSpec] = Field(default_factory=dict)
    resources: Dict[str, ResourceSpec] = Field(default_factory=dict)

    def _ensure_group_exists(self, group_name: str):
        if group_name not in self.groups:
            raise ValueError(f"Group '{group_name}' not found")

    def _ensure_resource_exists(self, resource_name: str):
        if resource_name not in self.resources:
            raise ValueError(f"Resource '{resource_name}' not found")

    def group_names(self):
        return self.groups.keys()

    def group(self, name):
        self._ensure_group_exists(name)
        return self.groups[name].model_dump()

    def add_group(self, group: GroupSpec):
        if group.name in self.groups:
            raise ValueError(f"Group '{group.name}' already exists")
        if len(self.groups) >= int(settings.group_limit):
            raise ValueError(f"Max group count reached, unable to add new group")
        self.groups[group.name] = group
        logger.info(f"Group '{group.name}' added")

    def delete_group(self, group_name: str):
        self._ensure_group_exists(group_name)
        if any(res.group == group_name for res in self.resources.values()):
            raise ValueError(f"Group '{group_name}' is still in use by resources")
        del self.groups[group_name]
        logger.info(f"Group '{group_name}' deleted")

    def grp_attr_update(self, name: str, updates: dict):
        self._ensure_group_exists(name)
        group = self.groups[name]

        for key, value in updates.items():
            if key == "attributes":
                if not isinstance(value, dict):
                    raise ValueError("attributes must be a dictionary")
                group.attributes = group.attributes.model_copy(update=value)
            elif key in group.model_attrs:
                setattr(group, key, value)
            else:
                raise ValueError(f"Unknown field '{key}' in group attribute update")

    def group_resources(self, name: str):
        self._ensure_group_exists(name)
        return [resource.model_dump() for resource in self.resources.values() if resource.group == name ]

    def resource_names(self):
        return self.resources.keys()

    def resource(self, name: str):
        self._ensure_resource_exists(name)
        return self.resources[name].model_dump()

    def add_resource(self, resource: ResourceSpec):
        if resource.name in self.resources:
            raise ValueError(f"Resource '{resource.name}' already exists")
        if resource.group not in self.groups:
            raise ValueError(f"Group '{resource.group}' does not exist")
        if len(self.resources) >= int(settings.resource_limit):
            raise ValueError(f"Max resource count reached, unable to add new resource")
        self.resources[resource.name] = resource
        logger.info(f"Resource '{resource.name}' added")

    def update_resource(self, resource_name: str, updates: dict):
        self._ensure_resource_exists(resource_name)
        resource = self.resources[resource_name]

        for key, value in updates.items():
            if key == "attributes":
                if not isinstance(value, dict):
                    raise ValueError("attributes must be a dictionary")
                resource.attributes = resource.attributes.model_copy(update=value)
            elif key in resource.model_fields:
                setattr(resource, key, value)
            else:
                raise ValueError(f"Unknown field '{key}' in resource attribute update")

    def delete_resource(self, resource_name: str):
        self._ensure_resource_exists(resource_name)
        # Ensure no other resource depends on this one
        for res_config in self.resources.values():
            if resource_name in res_config.dependsOn:
                raise ValueError(f"Resource '{resource_name}' is a dependency of '{res_config.name}'")
        del self.resources[resource_name]
        logger.info(f"Resource '{resource_name}' deleted")

    def res_attr(self, resource_name: str):
        self._ensure_resource_exists(resource_name)
        logger.debug(self.resources[resource_name])
        return self.resources[resource_name].attributes.model_dump()

    def res_attr_update(self, resource_name: str, updates: dict):
        self._ensure_resource_exists(resource_name)
        logger.debug(f"Updating attributes of resource '{resource_name}' with {updates}")
        resource = self.resources[resource_name]

        # Validate all keys
        for key in updates:
            if key not in resource.attributes.model_fields:
                raise ValueError(f"Unknown attribute '{key}' for resource '{resource_name}'")

        # Use model_copy to return a new instance with updates
        resource.attributes = resource.attributes.model_copy(update=updates)

    def res_dependency(self, resource_name: str):
        self._ensure_resource_exists(resource_name)
        return self.resources[resource_name].dependsOn

    def link_dependency(self, resource_name: str, dependency_name: str):
        self._ensure_resource_exists(resource_name)
        self._ensure_resource_exists(dependency_name)

        if dependency_name in self.resources[resource_name].dependsOn:
            raise ValueError(f"Resource '{resource_name}' already depends on '{dependency_name}'")

        self.resources[resource_name].dependsOn.append(dependency_name)
        logger.info(f"Added dependency: '{resource_name}' depends on '{dependency_name}'")

    def unlink_dependency(self, resource_name: str, dependency_name: str):
        self._ensure_resource_exists(resource_name)
        self._ensure_resource_exists(dependency_name)

        if dependency_name not in self.resources[resource_name].dependsOn:
            raise ValueError(f"Resource '{resource_name}' does not depend on '{dependency_name}'")

        self.resources[resource_name].dependsOn.remove(dependency_name)
        logger.info(f"Removed dependency: '{resource_name}' no longer depends on '{dependency_name}'")
