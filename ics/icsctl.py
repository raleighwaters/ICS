import argparse
import requests
import yaml
from pathlib import Path
import sys

from ics.settings import settings

API_BASE = f"http://localhost:{settings.api_port}"

def ping():
    try:
        r = requests.get(f"{API_BASE}/ping")
        print(r.json())
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


def get(resource_type, name=None):
    if resource_type not in ("resources", "groups"):
        print("Error: type must be 'resources' or 'groups'")
        sys.exit(1)

    if name:
        r = requests.get(f"{API_BASE}/{resource_type}/{name}")
        if r.status_code == 200:
            print(yaml.dump(r.json(), sort_keys=False))
        elif r.status_code == 404:
            print(f"{resource_type[:-1].capitalize()} '{name}' not found.")
            sys.exit(1)
        else:
            print(f"Error: {r.status_code} {r.text}")
            sys.exit(1)
    else:
        r = requests.get(f"{API_BASE}/{resource_type}")
        print(r.json())


def apply(file_path):
    try:
        with open(file_path) as f:
            docs = list(yaml.safe_load_all(f))
    except Exception as e:
        print(f"Error reading YAML: {e}")
        sys.exit(1)

    for doc in docs:
        kind = doc.get("kind")
        metadata = doc.get("metadata", {})
        spec = doc.get("spec", {})

        if kind == "Resource":
            payload = spec | {"name": metadata["name"], "group": metadata["group"]}
            response = requests.post(f"{API_BASE}/resources", json=payload)
        elif kind == "Group":
            payload = spec | {"name": metadata["name"]}
            response = requests.post(f"{API_BASE}/groups", json=payload)
        else:
            print(f"Unknown kind: {kind}")
            continue

        print(f"{kind}: {response.status_code} {response.text}")

def delete(resource_type, name):
    if resource_type not in ("resources", "groups"):
        print("Error: type must be 'resources' or 'groups'")
        sys.exit(1)

    r = requests.delete(f"{API_BASE}/{resource_type}/{name}")
    if r.status_code == 200:
        print(f"{resource_type[:-1].capitalize()} '{name}' deleted successfully.")
    elif r.status_code == 404:
        print(f"{resource_type[:-1].capitalize()} '{name}' not found.")
    else:
        print(f"Error: {r.status_code} {r.text}")


def main():
    parser = argparse.ArgumentParser(description="ICS CLI tool")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("ping", help="Check ICS server status")

    get_parser = subparsers.add_parser("get", help="List or get a resource/group")
    get_parser.add_argument("type", choices=["resources", "groups"])
    get_parser.add_argument("name", nargs="?", help="(Optional) name of resource/group to show")

    delete_parser = subparsers.add_parser("delete", help="Delete a resource or group")
    delete_parser.add_argument("type", choices=["resources", "groups"])
    delete_parser.add_argument("name", help="Name of the resource or group to delete")

    apply_parser = subparsers.add_parser("apply", help="Apply a YAML spec")
    apply_parser.add_argument("file", type=Path)

    args = parser.parse_args()

    if args.command == "ping":
        ping()
    elif args.command == "get":
        get(args.type, args.name)
    elif args.command == "delete":
        delete(args.type, args.name)
    elif args.command == "apply":
        apply(args.file)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
