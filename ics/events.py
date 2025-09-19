import logging
try:
    import queue
except ImportError:
    import Queue as queue  # Python2 version

from ics import metrics
from ics.settings import settings
from ics.alerts import AlertClient
from ics.states import ResourceStates, ONLINE_STATES, OFFLINE_STATES

logger = logging.getLogger(__name__)

event_queue = queue.Queue()

alert = AlertClient()


def trigger_event(event):
    """Add event to event queue.

    Args:
        event (obj): Event like object.

    """
    logger.debug('Resource({}) event triggered {}'.format(event.resource.name, event))
    event_queue.put(event)


def event_handler():
    """Continuously execute events in event queue"""
    while True:
        queue_size = event_queue.qsize()
        metrics.ics_engine_queue_length.labels(cluster_name=settings.cluster_name).set(queue_size)
        if queue_size > 0:
            logger.debug('Remaining events in event queue ({})'.format(queue_size))
        event = event_queue.get()
        logger.debug('Running event ({})'.format(event))

        # Catch and log all exceptions that occur and continue to process events
        try:
            event.run()
        except Exception:
            logger.exception('Event {} encountered an error:'.format(str(event)))
            alert.error(event.resource, "Error occurred while processing event. Please check logs.")
            continue

        del event


class Event:
    """Base event class"""
    def run(self):
        pass

    def __str__(self):
        return '{} for {}'.format(self.__class__.__name__, self.resource.name)


class PollEvent(Event):
    """Base poll event class"""
    def __init__(self, resource):
        self.resource = resource

    def run(self):
        pass


class PollRunEvent(PollEvent):
    def run(self):
        self.resource.poll()


class PollOnlineEvent(PollEvent):
    def run(self):
        if self.resource.state is not ResourceStates.FAULTED:
            self.resource.change_state(ResourceStates.ONLINE)


class PollOfflineEvent(PollEvent):
    def run(self):
        if self.resource.state is not ResourceStates.FAULTED:
            self.resource.change_state(ResourceStates.OFFLINE)


class PollUnknownEvent(PollEvent):
    def run(self):
        self.resource.change_state(ResourceStates.UNKNOWN)


class ResourceStateEvent(Event):
    """Base resource event class"""
    def __init__(self, resource, last_state):
        self.resource = resource
        self.last_state = last_state

    def run(self):
        pass


class ResourceOfflineEvent(ResourceStateEvent):
    def run(self):
        if self.last_state in ONLINE_STATES:
            self.resource.fault_count += 1
            metrics.ics_resource_faults_total.labels(
                resource_name=self.resource.name,
                cluster_name=settings.cluster_name
            ).inc()
            restart_limit = int(self.resource.attr_value('RestartLimit'))
            logger.info('Resource({}) Fault detected ({} of {})'.format(self.resource.name,
                                                                        self.resource.fault_count, restart_limit))
            logger.debug('Resource({}) last state: {}'.format(self.resource.name, self.last_state))

            if self.resource.fault_count >= restart_limit:
                logger.info('Resource({}) reached max fault count ({})'.format(self.resource.name,
                                                                               self.resource.attr_value('RestartLimit')))
                self.resource.change_state(ResourceStates.FAULTED)
            #elif self.resource.attr_value('AutoRestart') == 'true':
            else:
                self.resource.change_state(ResourceStates.STARTING)
        elif self.resource.propagate:
            self.resource.propagate = False  # Resource has successfully propagated from parent
            for parent in self.resource.parents:
                if parent.offline_ready():
                    logger.info('Resource({}) propagating offline to {} '.format(self.resource.name, parent.name))
                    parent.propagate = True
                    if parent.state is ResourceStates.ONLINE:
                        parent.change_state(ResourceStates.STOPPING)
                    elif parent.state is ResourceStates.OFFLINE:
                        # Needed to continue propagation even though resources is already offline
                        # Offline event is triggered again to propagate to parent resource
                        parent.change_state(ResourceStates.OFFLINE, force=True)
                    # TODO: to be more robust, add cases for when state is other than online or offline
                else:
                    logger.debug('Resource({}) Unable to stop, waiting for children to become offline'
                                 .format(parent.name))


class ResourceStoppingEvent(ResourceStateEvent):
    def run(self):
        self.resource.stop()


class ResourceOnlineEvent(ResourceStateEvent):
    def run(self):
        if self.last_state in OFFLINE_STATES:
            logger.warning('Resource({}) came online unexpectedly'.format(self.resource.name))
            alert.warning(self.resource, 'Resource came online by itself')
        elif self.resource.propagate:
            self.resource.propagate = False  # Resource has successfully propagated from children
            for child in self.resource.children:
                if child.online_ready():
                    logger.info('Resource({}) propagating online to {} '.format(self.resource.name, child.name))
                    child.propagate = True
                    if child.state in ResourceStates.OFFLINE:
                        child.change_state(ResourceStates.STARTING)
                    elif child.state is ResourceStates.ONLINE:
                        # Needed to continue propagation even though resources is already online
                        # Online event is triggered again to propagate to child resource
                        child.change_state(ResourceStates.ONLINE, force=True)
                    # TODO: to be more robust, add cases for when state is other than online or offline
                else:
                    logger.debug('Resource({}) Unable to start, waiting for parents '
                                 'to become online'.format(child.name))


class ResourceStartingEvent(ResourceStateEvent):
    def run(self):
        self.resource.start()


class ResourceFaultedEvent(ResourceStateEvent):
    def run(self):
        self.resource.flush()
        alert.error(self.resource, 'Resource faulted')
        # TODO: propagate any offline


class ResourceUnknownEvent(ResourceStateEvent):
    def run(self):
        if self.last_state is not ResourceStates.UNKNOWN:
            alert.warning(self.resource, 'Resource in unknown state')
