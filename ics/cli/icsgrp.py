import argparse
import requests
import sys

from ics.cli.common import API_BASE, epilog_text, print_table



def grp_online(name, node):
    pass


def grp_offline():
    pass


def grp_add():
    pass


def grp_delete():
    pass


def grp_enable():
    pass


def grp_disable():
    pass


def grp_enable_resources():
    pass


def grp_disable_resources():
    pass


def grp_state():
    pass


def grp_state_all():
    pass


def grp_clear():
    pass


def grp_flush():
    pass


def grp_resources():
    pass


def grp_list():
    pass


def grp_attr():
    pass


def grp_value():
    pass


def grp_modify():
    pass




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
        if len(group_list) == 0:
            results = grp_state_all()
            print_table(results)
        elif len(group_list) == 1:
            group_name = group_list[0]
            group_states = grp_state(group_name)
            table = []
            for state in group_states.items():
                table.append((group_name,) + state)

            print_table(table)
        else:
            results = grp_state_all(group_names=group_list)
            print_table(results)

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
        result = grp_resources(group_name)
        result.sort()
        for group_name in result:
            print(group_name)

    elif args.list is True:
        groups = grp_list()
        for group_name in groups:
            print(group_name)

    elif args.attr is not None:
        group_name = args.attr[0]
        result = grp_attr(group_name)
        print_table(result)

    elif args.value is not None:
        group_name = args.value[0]
        attr = args.value[1]
        result = grp_value(group_name, attr)
        print(result)

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
            try:
                timer = int(secondary_args.timeout[0])
            except ValueError:
                print('ERROR: Timeout parameter invalid.')
                sys.exit(1)
        else:
            timer = -1  # Negative timer means no countdown

        while timer != 0:
            group_states = grp_state(group_name, valid_nodes=True)

            if node is not None:
                if group_states[node] == state_name:
                    sys.exit(0)
            elif secondary_args.all:
                states = group_states.values()
                if list(set(states)) == [state_name]:
                    sys.exit(0)
            else:
                if state_name in group_states.values():
                    sys.exit(0)

            time.sleep(1)
            timer -= 1

        sys.exit(1)  # Exit with return code 1 when timeout is reached

    else:
        parser.print_help()







if __name__ == "__main__":
    main()

