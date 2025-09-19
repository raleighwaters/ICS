import logging
import random
import subprocess
import time

from ics import metrics
from ics import events
from ics.settings import settings
from ics.alerts import AlertClient
from ics.attributes import AttributeObject, resource_attributes, group_attributes
from ics.states import ResourceStates, GroupStates, ONLINE_STATES
from ics.utils import resource_log_name

from ics.models import ResourceSpec, GroupSpec

logger = logging.getLogger(__name__)

alert = AlertClient()


class Resource(AttributeObject):

    def __init__(self, name, group_name, init_state=ResourceStates.UNKNOWN):
        super(Resource, self).__init__()
        self.init_attr(resource_attributes)
        self.name = name
        self.state = None
        self.set_attr('Group', group_name)
        self.last_poll = int(time.time()) - random.randint(0, 60)  # Set at random times to prevent poll clustering
        self.poll_running = False
        self.fault_count = 0
        self.parents = []
        self.children = []
        self.propagate = False
        self.cmd_process = None
        self.cmd_type = None
        self.cmd_end_time = -1
        self.cmd_exit_code = 0

        # Initialize resource state
        self.set_state(init_state)

        # Initialize metrics
        metrics.ics_resource_faults_total.labels(resource_name=self.name, cluster_name=settings.cluster_name).inc(0)


    event_map = {
        ResourceStates.OFFLINE: events.ResourceOfflineEvent,
        ResourceStates.STARTING: events.ResourceStartingEvent,
        ResourceStates.ONLINE: events.ResourceOnlineEvent,
        ResourceStates.STOPPING: events.ResourceStoppingEvent,
        ResourceStates.FAULTED: events.ResourceFaultedEvent,
        ResourceStates.UNKNOWN: events.ResourceUnknownEvent
    }

    def to_spec(self) -> ResourceSpec:
        return ResourceSpec(
            name=self.name,
            group=self.attr_value("Group"),
            enabled=self.attr_value("Enabled") == "true",
            startProgram=self.attr_value("StartProgram"),
            stopProgram=self.attr_value("StopProgram"),
            monitorProgram=self.attr_value("MonitorProgram"),
            faultPropagation=self.attr_value("FaultPropagation") == "true",
            onlineRetryLimit=int(self.attr_value("OnlineRetryLimit")),
            restartLimit=int(self.attr_value("RestartLimit")),
            monitorOnly=self.attr_value("MonitorOnly") == "true",
            monitorInterval=int(self.attr_value("MonitorInterval")),
            offlineMonitorInterval=int(self.attr_value("OfflineMonitorInterval")),
            onlineTimeout=int(self.attr_value("OnlineTimeout")),
            offlineTimeout=int(self.attr_value("OfflineTimeout")),
            monitorTimeout=int(self.attr_value("MonitorTimeout")),
            load=int(self.attr_value("Load")),
        )

    def set_state(self, state: str):
        self.state = state
        state_map = {
            "offline": 0,
            "starting": 1,
            "online": 2,
            "stopping": 3,
            "faulted": 4,
            "unknown": 5
        }
        metrics.ics_resource_state.labels(
            resource_name=self.name,
            cluster_name=settings.cluster_name
        ).set(state_map[self.state])

    def change_state(self, new_state: ResourceStates, force=False):
        """Change state of resource and add event to queue.

        Args:
            new_state (str): New resource state.
            force (bool, opt): Force state change.

        Returns:
            bool: Returns stressfulness ot state change.

        """
        cur_state = self.state
        if not force:
            if new_state is cur_state:
                return False

        if self.attr_value('Enabled') == 'false' or self.attr_value('MonitorOnly') == 'true':
            self.state = ResourceStates.OFFLINE  # Set resource offline regardless of current state
            logger.info('Resource({}) Unable to change state, resource is disabled'.format(self.name))

            # When a resource is disabled, no state change will occur. However, subsequent event will be triggered to
            # act as a pass though in order to facilitate propagation.
            # Note: A new_state of online or offline can occur when a child or parent forces a state change to continue
            # propagation when resources is already in that state.
            if new_state in [ResourceStates.STARTING, ResourceStates.ONLINE]:
                event_class = events.ResourceOnlineEvent
                cur_state = ResourceStates.ONLINE  # Fake the current state for propagation
            elif new_state in [ResourceStates.STOPPING, ResourceStates.OFFLINE]:
                event_class = events.ResourceOfflineEvent
                cur_state = ResourceStates.OFFLINE  # Fake the current state for propagation
            else:
                logger.error('Resource({}) Attempted an invalid state change to {} when resource is disabled,'
                             ' no change will occur'.format(self.name, new_state))
                return False
        else:
            self.set_state(new_state)
            event_class = self.event_map[new_state]
            logger.info('Resource({}) Changing state from {} to {}'.format(self.name, cur_state, new_state))

        events.trigger_event(event_class(self, cur_state))

    def add_parent(self, resource):
        """Add parent dependency link to resource.

        Args:
            resource (obj): Parent resource object.

        """
        self.parents.append(resource)

    def remove_parent(self, resource):
        """Remove parent dependency link to resource.

        Args:
            resource (obj): Parent resource object.

        """
        self.parents.remove(resource)

    def dependencies(self):
        """Return a list of dependencies.

        Returns:
            list: List of resource names that are dependencies of this resource.

        """
        deps_list = []
        for parent in self.parents:
            deps_list.append(parent.name)
        return deps_list

    def add_child(self, resource):
        """Add child dependency link to resource.

        Args:
            resource (obj): Child resource object.

        """
        self.children.append(resource)

    def remove_child(self, resource):
        """Remove child dependency link to resource.

        Args:
            resource (obj): Child resource object.

        """
        self.children.remove(resource)

    def online_ready(self):
        """Determine weather resources parents are ready by checking for specific conditions

        Returns:
            bool: Readiness of parent dependencies

        """
        for parent in self.parents:
            logger.debug('Resource({}) Verifying state of {}'.format(self.name, parent.name))
            state = parent.state

            if parent.attr_value('Enabled') == 'false':
                logger.debug('Resource({}) Found {} to be disabled, skipping'.format(self.name, parent.name))
                continue
            elif parent.attr_value('MonitorOnly') == 'true':
                logger.debug('Resource({}) Found {} to be in monitory only, skipping'.format(self.name, parent.name))
                continue
            elif state is not ResourceStates.ONLINE:
                logger.debug('Resource({}) Found {} in state {} '
                             'not to be online unable to start yet'.format(self.name, parent.name, state))
                return False

        return True

    def offline_ready(self):
        """Determine weather resources children are ready by checking for specific conditions

        Returns:
            bool: Readiness of child dependencies

        """
        for child in self.children:
            logger.debug('Resource({}) Verifying state of {}'.format(self.name, child.name))
            state = child.state

            if child.attr_value('Enabled') == 'false':
                logger.debug('Resource({}) Found {} to be disabled, skipping'.format(self.name, child.name))
                continue
            elif child.attr_value('MonitorOnly') == 'true':
                logger.debug('Resource({}) Found {} to be in monitory only, skipping'.format(self.name, child.name))
                continue
            elif state is not ResourceStates.OFFLINE:
                logger.debug('Resource({}) Found {} in state {} '
                             'not to be offline unable to start yet'.format(self.name, child.name, state))
                return False

        return True

    def update_poll(self):
        """Update resource poll timer."""
        cur_time = int(time.time())
        if self.state in ONLINE_STATES:
            poll_interval = int(self.attr_value('MonitorInterval'))
        else:
            poll_interval = int(self.attr_value('OfflineMonitorInterval'))

        if cur_time - self.last_poll >= poll_interval and not self.poll_running:
            self.poll_running = True
            logger.debug('Resource({}) ready for interval monitoring poll'.format(self.name))
            self.probe()

    def _reset_cmd(self):
        """Reset executed command attributes."""
        self.cmd_process = None
        self.cmd_type = None
        self.poll_running = False
        self.cmd_end_time = -1

    def _run_cmd(self, cmd, cmd_type, timeout=None):
        """Run an resource command.

        Args:
            cmd (list): Command line command for resource.
            cmd_type (str): Command type.
            timeout (int, opt): Command execute timeout.

        """
        try:
            logger.debug('Resource({}) running command: {}'.format(self.name, ' '.join(cmd)))
            resource_log = resource_log_name()
            self.cmd_process = subprocess.Popen(cmd,
                                                stdout=open(resource_log, 'a'),
                                                stderr=open(resource_log, 'a'),
                                                close_fds=True)
            self.cmd_end_time = int(time.time()) + timeout
            self.cmd_type = cmd_type
        except IndexError:
            logger.error('Resource({}) unable to run command, no command given'.format(self.name))
            self._reset_cmd()
            if cmd_type == 'poll':
                self.reset_poll_counter()
        except (PermissionError, FileNotFoundError) as err:
            logger.error('Resource({}) unable to execute command, {}.'.format(self.name, str(err)))
            self._reset_cmd()
            if cmd_type == 'poll':
                self.reset_poll_counter()
        except Exception as err:
            logger.exception('Resource({}) command caught unknown exception {}'.format(self.name, err))
            self._reset_cmd()
            if cmd_type == 'poll':
                self.reset_poll_counter()

    def check_cmd(self):
        """Check if resource command has finished.

        Returns:
            bool: Stressfulness of command execution.

        """
        if self.cmd_process is not None:
            if self.cmd_process.poll() is not None:
                logger.debug('Resource({}) {} command returned'.format(self.name, self.cmd_type))
                self.cmd_exit_code = self.cmd_process.poll()
                return True
            elif int(time.time()) >= self.cmd_end_time:
                logger.warning('Resource({}) timeout occurred while attempting to {}'.format(self.name, self.cmd_type))
                alert.warning(self, 'Resource {} timeout'.format(self.cmd_type))
                self.cmd_process.kill()
                # TODO: add some action here
            else:
                return False
        else:
            return False

    poll_event_map = {
        110: events.PollOnlineEvent,
        100: events.PollOfflineEvent,
        -1: events.PollUnknownEvent
    }

    def handle_cmd(self):
        """Handle resource command return"""
        if self.cmd_type in ['start', 'stop']:
            if self.cmd_exit_code != 0:
                logger.warning('Resource({}) error occurred when running {} '
                               'command, return code {}'.format(self.name, self.cmd_type, self.cmd_exit_code))
            else:
                logger.debug('Resource({}) command {} ran successfully'.format(self.name, self.cmd_type))
            events.trigger_event(events.PollRunEvent(self))
        elif self.cmd_type == 'poll':
            if self.cmd_exit_code == 110:
                logger.debug('Resource({}) poll command found resource to be online'.format(self.name))
                event_class = self.poll_event_map[self.cmd_exit_code]
            elif self.cmd_exit_code == 100:
                logger.debug('Resource({}) poll command found resource to be offline'.format(self.name))
                event_class = self.poll_event_map[self.cmd_exit_code]
            else:
                logger.warning('Resource({}) error occurred when polling '
                               'resource, return code {}'.format(self.name, self.cmd_exit_code))
                event_class = self.poll_event_map[-1]

            self.reset_poll_counter()
            self.poll_running = False
            events.trigger_event(event_class(self))
        else:
            logger.error('Resource({}) received unknown command type: {}'.format(self.name, self.cmd_type))

        self._reset_cmd()

    def clear(self):
        """Clear faulted resource state."""
        self.fault_count = 0  # reset fault count
        if self.state is ResourceStates.FAULTED:
            self.change_state(ResourceStates.OFFLINE)

    def flush(self):
        """Flush resource out of transitions states."""
        self.propagate = False
        if self.cmd_process is not None:
            try:
                self.cmd_process.kill()
            except OSError:
                logger.error('Unable to kill process for resource ' + self.name)
                return
        self._reset_cmd()
        if self.state is ResourceStates.STARTING:
            self.change_state(ResourceStates.OFFLINE)
        elif self.state is ResourceStates.STOPPING:
            self.change_state(ResourceStates.ONLINE)

    def probe(self):
        """Generate a resource poll."""
        if self.attr_value('Enabled') == 'false':
            logger.info('Resource({}) Unable to probe, resource is not enabled.'.format(self.name))
        else:
            self.poll_running = True
            events.trigger_event(events.PollRunEvent(self))

    def start(self):
        """Run command to start resource."""
        logger.info('Resource({}) running command to start resource'.format(self.name))
        cmd = self.attr_value('StartProgram').split()
        if not cmd:
            logger.error('Resource({}) unable to start, attribute StartProgram not set'.format(self.name))
            self.flush()
            return
        online_timeout = int(self.attr_value('OnlineTimeout'))
        self._run_cmd(cmd, 'start', timeout=online_timeout)

    def stop(self):
        """Run command to stop resource."""
        logger.info('Resource({}) running command to stop resource'.format(self.name))
        cmd = self.attr_value('StopProgram').split()
        if not cmd:
            logger.error('Resource({}) unable to start, attribute StopProgram not set'.format(self.name))
            self.flush()
            return
        offline_timeout = int(self.attr_value('OfflineTimeout'))
        self._run_cmd(cmd, 'stop', timeout=offline_timeout)

    def poll(self):
        """Run command to poll resource."""
        logger.debug('Resource({}) running command to poll resource'.format(self.name))
        cmd = self.attr_value('MonitorProgram').split()
        if not cmd:
            logger.error('Resource({}) unable to monitor, attribute MonitorProgram not set'.format(self.name))
            self.poll_running = False
            self.flush()
            return
        monitor_timeout = int(self.attr_value('MonitorTimeout'))
        self._run_cmd(cmd, 'poll', timeout=monitor_timeout)

    def reset_poll_counter(self):
        """Reset poll timer counter."""
        self.last_poll = int(time.time())


class Group(AttributeObject):

    def __init__(self, name):
        super(Group, self).__init__()
        self.init_attr(group_attributes)
        self.name = name
        self.members = []  # TODO: rename member for group class?

    def to_spec(self) -> GroupSpec:
        return GroupSpec(
            name=self.name,
            systemList=self.attr_value("SystemList"),
            enabled=self.attr_value("Enabled") == "true",
            autoStart=self.attr_value("AutoStart") == "true",
            ignoreDisabled=self.attr_value("IgnoreDisabled") == "true",
            parallel=self.attr_value("Parallel") == "true",
        )

    def state(self):
        """Get state of group by checking state of member resources.

        Returns:
            str: Group state.

        """
        if not self.members:
            return GroupStates.UNKNOWN  # A group with no resources has an unknown state

        # Get all unique resource states
        resource_states = []
        for member in self.members:
            if self.attr_value('IgnoreDisabled') == 'true' and member.attr_value('Enabled') == 'false':
                continue
            else:
                resource_states.append(member.state)

        states = list(set(resource_states))

        if len(states) == 0:
            return GroupStates.OFFLINE
        elif len(states) > 1:
            return GroupStates.PARTIAL  # TODO: having multiple states does not necessarily mean a partial state
        else:
            if states[0] == ResourceStates.ONLINE:
                return GroupStates.ONLINE
            elif states[0] == ResourceStates.OFFLINE:
                return GroupStates.OFFLINE
            elif states[0] == ResourceStates.STARTING:
                return GroupStates.PARTIAL
            elif states[0] == ResourceStates.STOPPING:
                return GroupStates.PARTIAL
            elif states[0] == ResourceStates.FAULTED:
                return GroupStates.FAULTED
            elif states[0] == ResourceStates.UNKNOWN:
                return GroupStates.UNKNOWN
            else:
                return GroupStates.UNKNOWN

    def load(self):
        """Total resource load of group.

        Returns:
            int: total resource load.

        """
        total_load = 0
        for member in self.members:
            total_load += int(member.attr_value('Load'))

        return total_load

    def add_resource(self, resource):
        """Add group resource.

        Args:
            resource (obj): Resource object to add to group.

        """
        self.members.append(resource)

    def delete_resource(self, resource):
        """Delete group resources.

        Args:
            resource (obj): Resource object to remove from group.

        """
        self.members.remove(resource)

    def enable_resources(self):
        """Enable group resources."""
        for member in self.members:
            member.set_attr('Enabled', 'true')

    def disable_resources(self):
        """Disable group resources."""
        for member in self.members:
            member.set_attr('Enabled', 'false')

    def start(self):
        """Start group resources."""
        if self.attr_value('Enabled') == 'false':
            logger.info('Unable to start, group is not enabled')
            return

        self.flush()

        # Start all resources which don't have parent resources to initiate group online
        for resource in self.members:
            if not resource.parents:
                resource.propagate = True
                if resource.state is not ResourceStates.ONLINE:
                    resource.change_state(ResourceStates.STARTING)
                else:
                    # Force resource to run online event to initiate propagation
                    # event even thought resource is already online
                    resource.change_state(ResourceStates.ONLINE, force=True)

    def stop(self):
        """Stop group resources."""
        if self.attr_value('Enabled') == 'false':
            logger.info('Unable to start, group is not enabled')
            return

        self.flush()

        # Stop all resources which don't have children resources to initiate group online
        for resource in self.members:
            if not resource.children:
                resource.propagate = True
                if resource.state is not ResourceStates.OFFLINE:
                    resource.change_state(ResourceStates.STOPPING)
                else:
                    # Force resource to run offline event to initiate propagation
                    # event even though resource is already offline
                    resource.change_state(ResourceStates.OFFLINE, force=True)

    def flush(self):
        """Flush group resources in transition states."""
        for resource in self.members:
            resource.flush()

    def clear(self):
        """Clear group resource faults."""
        for resource in self.members:
            resource.clear()
