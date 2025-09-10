import argparse
import requests
import sys
import time

from ics.cli.common import API_BASE, epilog_text, check_response, print_table


def res_online(name: str, node: str):
    response = requests.put(f"{API_BASE}/resources/{name}/state", json={"state": "online", "node": node})
    check_response(response)


def res_offline(name: str, node: str):
    response = requests.put(f"{API_BASE}/resources/{name}/state", json={"state": "offline", "node": node})
    check_response(response)


def res_add(name: str, group: str):
    payload = {"name": name, "group": group}
    response = requests.post(f"{API_BASE}/resources", json=payload)
    check_response(response)


def res_delete(name: str):
    response = requests.delete(f"{API_BASE}/resources/{name}")
    check_response(response)


def res_state(name: str):
    response = requests.get(f"{API_BASE}/resources/{name}/state")
    check_response(response)
    resource_states = response.json()["data"]
    print(resource_states)
    table = []
    for state in resource_states.items():
        table.append((name,) + state)

    print_table(table)


def res_state_all():
    response = requests.get(f"{API_BASE}/state/resources")
    check_response(response)
    try:
        json_data = response.json()["data"]
    except TypeError:
        print("Error")
        sys.exit(1)

    table = []
    for resource_name, node_map in json_data.items():
        for node_name, state in node_map.items():
            table.append((resource_name, node_name, state))

    print_table(table)


def res_link(name: str, dependency: str):
    response = requests.put(f"{API_BASE}/resources/{name}/dependency/{dependency}")
    check_response(response)


def res_unlink(name: str, dependency: str):
    response = requests.delete(f"{API_BASE}/resources/{name}/dependency/{dependency}")
    check_response(response)


def res_clear(name: str):
    response = requests.get(f"{API_BASE}/resources/{name}/clear")
    check_response(response)


def res_probe(name: str):
    response = requests.get(f"{API_BASE}/resources/{name}/probe")
    check_response(response)


def res_dep(names: list):
    table = []
    for name in names:
        response = requests.get(f"{API_BASE}/resources/{name}")
        check_response(response)
        json_data = response.json()["data"]["dependsOn"]
        group_name = response.json()["data"]["group"]
        table.extend([(group_name, name, dep) for dep in json_data])

    print_table(table, header=["Group", "Resource", "Dependency"], col_sort=0)


def res_list():
    response = requests.get(f"{API_BASE}/resources")
    for resource in response.json()["resources"]:
        print(resource)


def res_attr(name: str):
    response = requests.get(f"{API_BASE}/resources/{name}")
    check_response(response)
    json_data = response.json()["data"]["attributes"]
    table = [(attribute, value) for attribute, value in json_data.items()]
    print_table(table)


def res_value(name: str, attribute: str):
    response = requests.get(f"{API_BASE}/resources/{name}")
    check_response(response)
    json_data = response.json()["data"]["attributes"]
    try:
        attribute_value = json_data[attribute]
    except KeyError:
        print(f"ERROR: Invalid attribute name '{attribute}'")
        sys.exit(1)

    print(attribute_value)


def res_modify(name: str, attribute: str, value: str):
    response = requests.patch(f"{API_BASE}/resources/{name}/attributes", json={attribute: value})
    check_response(response)


def res_wait(name: str, state: str, timeout=None, node=None, check_all_nodes=False):
    if timeout is not None:
        timer = int(timeout)
    else:
        timer = -1  # Negative timer means no countdown, wait forever

    while timer != 0:
        response = requests.get(f"{API_BASE}/resources/{name}/state")
        check_response(response)
        resource_states = response.json()["data"]

        if node is not None:
            if resource_states[node] == state:
                sys.exit(0)
        elif check_all_nodes:
            states = resource_states.values()
            if list(set(states)) == [state]:
                sys.exit(0)
        else:
            if state in resource_states.values():
                sys.exit(0)

        time.sleep(1)
        timer -= 1

    sys.exit(1)  # Exit with return code 1 when timeout is reached


def main():
    description_text = 'Manage ICS resources'
    parser = argparse.ArgumentParser(description=description_text, epilog=epilog_text, allow_abbrev=False)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('-online', nargs=1, metavar='<res> -sys <system>', help='bring resource online')
    group.add_argument('-offline', nargs=1, metavar='<res> -sys <system>', help='bring resource offline')
    group.add_argument('-add', nargs=2, metavar=('<res>', '<group>'), help='add new resource')
    group.add_argument('-delete', nargs=1, metavar='<res>', help='delete existing resource')
    group.add_argument('-state', nargs='*', metavar='<res>', help='print current state of resource')
    group.add_argument('-link', nargs=2, metavar=('<res>', '<dependency>'),
                       help='create dependency link between two resources')
    group.add_argument('-unlink', nargs=2, metavar=('<res>', '<dependency>'),
                       help='remove dependency link between two resources')
    group.add_argument('-clear', nargs=1, metavar='<res>', help='remove fault status')
    group.add_argument('-probe', nargs=1, metavar='<res>', help='probe a resource')
    group.add_argument('-dep', nargs='*', metavar='<res>', help='print dependencies')
    group.add_argument('-list', action='store_true', help='print list of all resources')
    group.add_argument('-attr', nargs=1, metavar='<res>', help='print resource attributes')
    group.add_argument('-value', nargs=2, metavar=('<res>', '<attr>'), help='print resource  attribute value')
    group.add_argument('-modify', nargs=argparse.REMAINDER, metavar='<res> <attr> <value>',
                       help='modify resource attribute')
    group.add_argument('-wait', nargs=2, metavar=('<res>', '<state> [ -timeout <timeout> ] [ -sys <sys> | -all ]'),
                       help='wait for resource to change state')

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
    secondary_parser.add_argument('-timeout', nargs=1, type=int)
    secondary_args = secondary_parser.parse_args(primary_args[1])

    if args.online is not None:
        resource_name = args.online[0]
        if secondary_args.sys is not None:
            system_name = secondary_args.sys[0]
            res_online(resource_name, system_name)
        else:
            print('ERROR: system must be specified.')
            sys.exit(1)

    elif args.offline is not None:
        resource_name = args.offline[0]
        if secondary_args.sys is not None:
            system_name = secondary_args.sys[0]
            res_offline(resource_name, system_name)
        else:
            print('ERROR: system must be specified.')
            sys.exit(1)

    elif args.add is not None:
        resource_name = args.add[0]
        group_name = args.add[1]
        res_add(resource_name, group_name)

    elif args.delete is not None:
        resource_name = args.delete[0]
        res_delete(resource_name)

    elif args.state is not None:
        resource_list = args.state
        if len(resource_list) == 1:
            resource_name = resource_list[0]
            res_state(resource_name)
        else:
            res_state_all()

    elif args.link is not None:
        resource_name = args.link[0]
        dependency_name = args.link[1]
        res_link(resource_name, dependency_name)

    elif args.unlink is not None:
        resource_name = args.unlink[0]
        dependency_name = args.unlink[1]
        res_unlink(resource_name, dependency_name)

    elif args.clear is not None:
        resource_name = args.clear[0]
        res_clear(resource_name)

    elif args.probe is not None:
        resource_name = args.probe[0]
        res_probe(resource_name)

    elif args.dep is not None:
        res_dep(args.dep)

    elif args.list is True:
        res_list()

    elif args.attr is not None:
        resource_name = args.attr[0]
        res_attr(resource_name)

    elif args.value is not None:
        resource_name = args.value[0]
        attr_name = args.value[1]
        res_value(resource_name, attr_name)

    elif args.modify is not None:
        if len(args.modify) < 3:
            parser.print_usage()
            print('error: argument -modify: expected 3 arguments')
            sys.exit(1)
        else:
            resource_name = args.modify[0]
            attr = args.modify[1]
            value = ' '.join(args.modify[2:])

        res_modify(resource_name, attr, value)

    elif args.wait is not None:
        resource_name, state_name = args.wait
        if secondary_args.timeout is not None:
            timeout = secondary_args.timeout[0]
        else:
            timeout = None

        res_wait(resource_name, state_name, node=secondary_args.sys, timeout=timeout, check_all_nodes=secondary_args.all)

    else:
        parser.print_help()


if __name__ == "__main__":
    try:
        main()
    except requests.exceptions.ConnectionError as err:
        print("Error: Unable to connect to the ICS server.")
        sys.exit(1)
