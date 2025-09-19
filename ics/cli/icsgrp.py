import argparse
import time

import requests
import sys

from ics.cli.common import API_BASE, epilog_text, print_table, check_response, format_attribute
from icsres import res_modify

def grp_online(name: str, node=None):
    payload = {"action": "online"}
    if node is not None:
        payload["node"] = node

    response = requests.put(f"{API_BASE}/groups/{name}/state", json=payload)
    check_response(response)


def grp_offline(name: str, node=None):
    payload = {"action": "offline"}
    if node is not None:
        payload["node"] = node

    response = requests.put(f"{API_BASE}/groups/{name}/state", json=payload)
    check_response(response)


def grp_add(name: str):
    response = requests.post(f"{API_BASE}/groups", json={"name": name})
    check_response(response)


def grp_delete(name: str):
    response = requests.delete(f"{API_BASE}/groups/{name}")
    check_response(response)

def grp_enable(name: str):
    response = requests.patch(f"{API_BASE}/groups/{name}/attributes", json={"enabled": "true"})
    check_response(response)


def grp_disable(name: str):
    response = requests.patch(f"{API_BASE}/groups/{name}/attributes", json={"enabled": "false"})
    check_response(response)


def grp_enable_resources(name: str):
    response = requests.get(f"{API_BASE}/groups/{name}/resources")
    check_response(response)
    resource_names = [resource["name"] for resource in response.json()["data"]]
    for resource_name in resource_names:
        res_modify(resource_name, "enabled", "true")


def grp_disable_resources(name: str):
    response = requests.get(f"{API_BASE}/groups/{name}/resources")
    check_response(response)
    resource_names = [resource["name"] for resource in response.json()["data"]]
    for resource_name in resource_names:
        res_modify(resource_name, "enabled", "false")


def grp_state(name: str):
    response = requests.get(f"{API_BASE}/groups/{name}/state")
    check_response(response)
    group_states = response.json()["data"]
    table = []
    for state in group_states.items():
        table.append((name,) + state)

    print_table(table)


def grp_state_all():
    response =  requests.get(f"{API_BASE}/state/groups")
    check_response(response)
    try:
        json_data = response.json()["data"]
    except TypeError:
        print("ERROR: ")
        sys.exit(1)

    table = []
    for group_name, node_map in json_data.items():
        for node_name, state in node_map.items():
            table.append((group_name, node_name, state))

    print_table(table)


def grp_clear(name: str, node: str):
    response = requests.get(f"{API_BASE}/groups/{name}/state", json={"action": "clear"})
    check_response(response)


def grp_flush(name: str, node: str):
    response = requests.get(f"{API_BASE}/groups/{name}/state", json={"action": "flush"})
    check_response(response)


def grp_resources(name: str):
    response = requests.get(f"{API_BASE}/groups/{name}/resources")
    check_response(response)
    resource_names = [resource["name"] for resource in response.json()["data"]]
    resource_names.sort()
    for resource_name in resource_names:
        print(resource_name)


def grp_list():
    response = requests.get(f"{API_BASE}/groups")
    check_response(response)
    for group in response.json()["data"]["groups"]:
        print(group)


def grp_attr(name: str):
    response = requests.get(f"{API_BASE}/groups/{name}")
    check_response(response)
    json_data = response.json()["data"]["attributes"]
    table = [(attribute, value) for attribute, value in json_data.items()]
    print_table(table)


def grp_value(name: str, attribute: str):
    response = requests.get(f"{API_BASE}/groups/{name}")
    check_response(response)
    json_data = response.json()["data"]["attributes"]
    try:
        attribute_value = json_data[attribute]
    except KeyError:
        print(f"ERROR: Invalid attribute name '{attribute}'")
        sys.exit(1)

    print(attribute_value)


def grp_modify(name: str, attribute: str, value: str):
    response = requests.patch(f"{API_BASE}/groups/{name}/attributes", json={format_attribute(attribute): value})
    check_response(response)


def grp_wait(name: str, state: str, timeout=None, node=None):
    if timeout is not None:
        timer = int(timeout)
    else:
        timer = -1  # Negative timer means no countdown, wait forever

    while timer != 0:
        response = requests.get(f"{API_BASE}/groups/{name}/state")
        check_response(response)
        group_states = response.json()["data"]

        if node is not None:
            if group_states[node]["state"] == state:
                sys.exit(0)

        else:
            if state in group_states.values():
                sys.exit(0)



        time.sleep(1)
        timer -= 1

    sys.exit(1)


def main():
    description_text = 'Manage ICS service groups'
    parser = argparse.ArgumentParser(description=description_text, epilog=epilog_text, allow_abbrev=False)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('-online', nargs=1, metavar='<group> [-sys <system>]', help='bring group online')
    group.add_argument('-offline', nargs=1, metavar='<group> [-sys <system>]', help='bring group offline')
    group.add_argument('-add', nargs=1, metavar='<group>', help='add new resource')
    group.add_argument('-delete', nargs=1, metavar='<group>', help='delete existing group')
    group.add_argument('-enable', nargs=1, metavar='<group>', help='enable resources for a group')
    group.add_argument('-disable', nargs=1, metavar='<group>', help='disable resources for a group')
    group.add_argument('-enableresources', nargs=1, metavar='<group>', help='enable all resources for a group')
    group.add_argument('-disableresources', nargs=1, metavar='<group>', help='disable all resources for a group')
    group.add_argument('-state', nargs='*', metavar='<group>', help='print current state of resource')
    group.add_argument('-clear', nargs=2, metavar=('<group>', '<system>'), help='remove fault status')
    group.add_argument('-flush', nargs=2, metavar=('<group>', '<system>'), help='flush group')
    group.add_argument('-resources', nargs=1, metavar='<group>', help='list all resources for a given group')
    group.add_argument('-list', action='store_true', help='print list of all groups')
    group.add_argument('-attr', nargs=1, metavar='<group>', help='print group attributes')
    group.add_argument('-value', nargs=2, metavar=('<group>', '<attr>'), help='print group attribute value')
    group.add_argument('-modify', nargs='*', metavar='<group> <attr> <value>',
                       help='modify group attribute')
    group.add_argument('-wait', nargs=2, metavar=('<group>', '<state> [ -timeout <timeout> ] [ -sys <sys> | -all ]'),
                       help='wait for group to change state')

    primary_args = parser.parse_known_args()
    args = primary_args[0]

    if len(sys.argv) <= 1:
        parser.print_help()
        sys.exit()

    secondary_parser = argparse.ArgumentParser()
    secondary_parser.add_argument('-sys', nargs=1)
    secondary_parser.add_argument('-all', action='store_true')
    secondary_parser.add_argument('-append', nargs=1)
    secondary_parser.add_argument('-remove', nargs=1)
    secondary_parser.add_argument('-timeout', nargs=1)
    secondary_args = secondary_parser.parse_args(primary_args[1])


    if args.online is not None:
        group_name = args.online[0]
        if secondary_args.sys is not None:
            system_name = secondary_args.sys[0]
            grp_online(group_name, node=system_name)
        else:
            grp_online(group_name)

    elif args.offline is not None:
        group_name = args.offline[0]
        if secondary_args.sys is not None:
            system_name = secondary_args.sys[0]
            grp_offline(group_name, node=system_name)
        else:
            grp_offline(group_name)

    elif args.add is not None:
        group_name = args.add[0]
        grp_add(group_name)

    elif args.delete is not None:
        group_name = args.delete[0]
        grp_delete(group_name)

    elif args.enable is not None:
        group_name = args.enable[0]
        grp_enable(group_name)

    elif args.disable is not None:
        group_name = args.disable[0]
        grp_disable(group_name)

    elif args.enableresources is not None:
        group_name = args.enableresources[0]
        grp_enable_resources(group_name)

    elif args.disableresources is not None:
        group_name = args.disableresources[0]
        grp_disable_resources(group_name)

    elif args.state is not None:
        group_list = args.state  # List of provided group names
        if len(group_list) == 1:
            group_name = group_list[0]
            grp_state(group_name)
        else:
            grp_state_all()

    elif args.clear is not None:
        group_name = args.clear[0]
        system_name = args.clear[1]
        grp_clear(group_name, system_name)

    elif args.flush is not None:
        group_name = args.flush[0]
        system_name = args.flush[1]
        grp_flush(group_name, system_name)

    elif args.resources is not None:
        group_name = args.resources[0]
        grp_resources(group_name)

    elif args.list is True:
        grp_list()

    elif args.attr is not None:
        group_name = args.attr[0]
        grp_attr(group_name)

    elif args.value is not None:
        group_name = args.value[0]
        attr = args.value[1]
        grp_value(group_name, attr)

    elif args.modify is not None:
        if len(args.modify) == 2:
            group_name = args.modify[0]
            attr = args.modify[1]
            if secondary_args.append is not None:
                value = secondary_args.append[0]
                grp_modify(group_name, attr, value, append=True)
            elif secondary_args.remove is not None:
                value = secondary_args.remove[0]
                grp_modify(group_name, attr, value, remove=True)
            else:
                print('error: argument -modify: expected use of -append or -remove with 2 arguments')
                sys.exit(1)

        elif len(args.modify) == 3:
            group_name = args.modify[0]
            attr = args.modify[1]
            value = ' '.join(args.modify[2:])
            grp_modify(group_name, attr, value)
        else:
            parser.print_usage()
            print('error: argument -modify: expected 2 or 3 arguments')
            sys.exit(1)

    elif args.wait is not None:
        group_name, state_name = args.wait

        if secondary_args.sys is None:
            node = None
        else:
            node = secondary_args.sys[0]

        if secondary_args.timeout is not None:
            timeout = secondary_args.timeout[0]
        else:
            timeout = None

        grp_wait(group_name, state_name, node=node, timeout=timeout)

    else:
        parser.print_help()


if __name__ == "__main__":
    try:
        main()
    except requests.exceptions.ConnectionError as err:
        print("ERROR: Unable to connect to the ICS server")
        sys.exit(1)
