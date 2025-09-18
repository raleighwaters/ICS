import json
import logging
import os

from ics.settings import settings
from ics.entities import get_resource
from ics.entities import grp_add
from ics.entities import res_add
from ics.entities import res_link

logger = logging.getLogger(__name__)


def read_json(filename):
    """Read data from configuration file and return data"""
    try:
        with open(filename, 'r') as file:
            return json.load(file)
    except IOError as error:
        logger.error('Unable to load config file {}, {}'.format(filename, str(error)))
        raise


def write_json(filename, data):
    """Write configuration data in json to file"""
    try:
        with open(filename, 'w') as file:
            json.dump(data, file, indent=4, sort_keys=True)
    except IOError as error:
        logger.error('Unable to save config file {}, {}'.format(filename, str(error)))
        raise


def load_config():
    """Read ICS configuration from file"""
    logger.info('Loading from config file')
    if not os.path.isfile(settings.conf_file):
        logger.info('No config file found, skipping load')
        return

    data_dict = read_json(settings.conf_file)

    for group_name in data_dict.keys():
        grp_add(group_name)
        for resource_name in data_dict[group_name]:
            res_add(resource_name, group_name)
            resource = get_resource(resource_name)
            for attr_name in data_dict[group_name][resource_name]['attributes'].keys():
                resource.attr[attr_name] = str(data_dict[group_name][resource_name]['attributes'][attr_name])

    # Links need to done in separate loop to guarantee parent
    # resources are created when establishing a link
    for group_name in data_dict.keys():
        for resource_name in data_dict[group_name]:
            for parent_name in data_dict[group_name][resource_name]['dependencies']:
                res_link(parent_name, resource_name)

    logger.debug('Resource configuration loaded from file {}'.format(settings.conf_file))


def write_config(data):
    """Save ICS configuration to file"""
    #data_dict = {}
    #default_attr = resource_attributes['resource']

    #for group in groups.values():
    #    group_name = group.name
    #    data_dict[group_name] = {}
    #    for resource in group.members:
    #        resource_name = resource.name
    #        data_dict[group_name][resource_name] = {}
    #        data_dict[group_name][resource_name]['attributes'] = {}
    #        for attr_name in resource.attr.keys():
    #            attr_value = resource.attr[attr_name]
    #             if attr_value != default_attr[attr_name]['default']:
    #                 data_dict[group_name][resource_name]['attributes'][attr_name] = attr_value
    #         data_dict[group.name][resource_name]['dependencies'] = []
    #         for parent in resource.parents:
    #             data_dict[group_name][resource_name]['dependencies'].append(parent.name)

    if not os.path.isdir(settings.conf_dir):
        try:
            os.makedirs(settings.conf_dir)
        except OSError as e:
            logger.error('Unable to create config directory: {}'.format(settings.conf_dir))
            logger.error('Reason: {}'.format(e))

    write_json(settings.conf_file, data)
