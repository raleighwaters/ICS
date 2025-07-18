import logging
import os
from datetime import datetime

try:
    import queue
except ImportError:
    import Queue as queue  # Python2 version

import Pyro4 as Pyro

from ics import mail
from ics.settings import settings
from ics.utils import alert_log_name
from ics.utils import engine_conn
from ics.utils import alert_conn

logger = logging.getLogger(__name__)

CRITICAL = 40
ERROR = 30
WARNING = 20
INFO = 10
NOTSET = 0

_level_names = {
    CRITICAL: 'CRITICAL',
    ERROR: 'ERROR',
    WARNING: 'WARNING',
    INFO: 'INFO',
    NOTSET: 'NOTSET',
    'CRITICAL': CRITICAL,
    'ERROR': ERROR,
    'WARNING': WARNING,
    'INFO': INFO,
    'NOTSET': NOTSET
}

alert_html_template_file = os.path.dirname(__file__) + '/templates/alert.html'


def get_level_name(level):
    """Return the string representation of an alert level.

    Args:
        level: Alert level

    Returns:
        Alert level name.

    """
    return _level_names[level]


def load_html_template(filename):
    """Load HTML template from file.

    Args:
        filename (str): HTML template filename.

    Returns:
        str: HTML template.

    """
    with open(filename, 'r') as f:
        return f.read()


def log_alert(alert):
    """Log alert using alert object.

    Args:
        alert (obj): Alert object.

    """
    with open(alert_log_name(), 'a+') as alert_log_file:
        alert_log_file.write(str(alert) + '\n')


def create_alert(resource, msg, level):
    """Create alert object from resource object.

    Args:
        resource (obj): Resource object.
        msg (str): Alert message.
        level (int): Alert level number.

    Returns:
        obj: Alert named tuple.

    """
    return Alert(resource.name, resource.attr_value('Group'), level, msg)


def create_test_alert(msg, level):
    """Create alert object for testing.

    Args:
        msg (str): Alert message.
        level (int): Alert level number.

    Returns:
        obj: Alert named tuple.

    """
    return Alert('Test_Resource', 'Test_Group', level, msg)


class Alert:
    """Alert object."""

    def __init__(self, resource, group, level, msg, node=settings.hostname, time=None):
        self.resource = resource
        self.group = group
        self.node = node
        self.level = level
        self.msg = msg
        if time is None:
            self.time = datetime.now().strftime("%m/%d/%Y %H:%M:%S")
        else:
            self.time = time

    def __str__(self):
        return ' '.join([self.time, get_level_name(self.level), settings.cluster_name, self.group, self.resource,
                         '\"' + self.msg + '\"'])

    def html(self, template):
        """Render alert as HTML.

        Args:
            template (str): HTML alert template.

        Returns:
            str: HTML to used to represent an alert.

        """
        return template.format(message=self.msg, system_name=settings.cluster_name, host_name=settings.hostname,
                               group_name=self.group, resource_name=self.resource, event_time=self.time)

    def asdict(self):
        """Alert information in dict format. Mainly used to send alert over serialization.

        Returns:
            dict: Alert as a dict.

        """
        return {
            'resource': self.resource,
            'group': self.group,
            'node': self.node,
            'time': self.time,
            'level': self.level,
            'msg': self.msg
        }


class AlertClient:
    """Alert interface for creating alerts.

    Attributes:
        self.alert_server_conn(obj): Alert server pyro connection.

    """

    def __init__(self):
        self.alert_server_conn = alert_conn()

    def critical(self, resource, msg):
        """Send alert with critical level.

        Args:
            resource (obj): Resource object.
            msg (str): Alert message.

        """
        logger.debug('Resource({}) Alert generated: {} '.format(resource.name, msg))
        alert = create_alert(resource, msg, CRITICAL)
        self.send_alert(alert)

    def error(self, resource, msg):
        """Send alert with error level.

        Args:
            resource (obj): Resource object.
            msg (str): Alert message.

        """
        logger.debug('Resource({}) Alert generated: {} '.format(resource.name, msg))
        alert = create_alert(resource, msg, ERROR)
        self.send_alert(alert)

    def warning(self, resource, msg):
        """Send alert with warning level.

        Args:
            resource (obj): Resource object
            msg (str): Alert message.

        """
        logger.debug('Resource({}) Alert generated: {} '.format(resource.name, msg))
        alert = create_alert(resource, msg, WARNING)
        self.send_alert(alert)

    def test(self, msg):
        """Send test alert message.

        Args:
            msg (str): Alert message.

        """
        logger.debug('Test alert generated: {} '.format(msg))
        alert = create_test_alert(msg, WARNING)
        self.send_alert(alert)

    def send_alert(self, alert):
        """Send alert to ICS alert server.

            Note: The alert must be sent as a dict, due to pyro not being able to send a serialized custom class.

        Args:
            alert (obj): Alert object.

        """
        self.alert_server_conn.add_alert(alert.asdict())


class AlertHandler:
    """Handle alerts in queue.

    Attributes:
        alert_queue(obj): Alert object queue
        alert_level(int): Alert level in integer format.
        html_template(str): Alert email html template text
        engine_conn(obj): Engine server pyro connection

    """

    def __init__(self):
        self.alert_queue = queue.Queue()
        self.alert_level = NOTSET
        self.html_template = load_html_template(alert_html_template_file)
        self.engine_conn = engine_conn()

    def update_alert_level(self):
        """Get alert level threshold of handler."""
        try:
            new_alert_level = self.engine_conn.node_value('AlertLevel')
            logger.debug('Updated alert level from engine: ' + str(new_alert_level))
            new_alert_level_int = get_level_name(new_alert_level)
            if new_alert_level_int != self.alert_level:
                logger.info('Alert level changed from {} to {}'.format(get_level_name(self.alert_level),
                                                                       get_level_name(new_alert_level_int)))
            self.alert_level = new_alert_level_int
        except KeyError as err:
            logger.error('Alert level received from engine is invalid: ' + str(err))
        except Pyro.errors.CommunicationError:
            logger.error("Unable to connect to ICS engine to retrieve alert level")

    def recipients(self):
        """Get Alert recipients email addressees.

        Returns:
            list: Alert recipients email addressees.
        """
        try:
            emails = self.engine_conn.node_value('AlertRecipients')
        except Pyro.errors.CommunicationError:
            logger.error("Unable to connect to ICS engine to retrieve alert recipients")
            emails = []

        return emails

    @Pyro.expose
    def add_alert(self, alert_dict):
        """Add alert to alert handler queue.

        Args:
            alert_dict(dict): Alert in dict format.

        """
        alert = Alert(alert_dict['resource'], alert_dict['group'], alert_dict['level'], alert_dict['msg'],
                      node=alert_dict['node'], time=alert_dict['time'])

        logger.info('Alert generated ' + str(alert))
        self.alert_queue.put(alert)

    def mail_alert(self, alert, template):
        """Mail alert.

        Args:
            alert (obj): Alert object.
            template (str): HTML template.

        """
        recipients = self.recipients()
        logger.debug('Recipient list: ' + str(recipients))
        if not recipients:
            logger.warning('Alert recipient list is empty, no alerts sent')
        else:
            for recipient in recipients:
                logger.info('Sending alert to {}'.format(recipient))
                sender = 'ics@' + settings.hostname
                subject = 'ICS {} Alert - {}'.format('Warning', alert.resource)
                body = alert.html(template)
                try:
                    mail.send_html(recipient, sender, subject, body)
                except ConnectionRefusedError as err:
                    logger.error('Unable to send mail: {}'.format(err))
                except Exception as err:
                    logger.exception('Unknown exception occurred: ' + str(err))

    def run(self):
        """Continuously read and execute alerts from alert queue."""
        while True:
            alert = self.alert_queue.get()  # Blocking until new alert available.
            self.update_alert_level()
            logger.debug('Alert level: ' + str(self.alert_level))
            if alert.level >= self.alert_level:
                log_alert(alert)
                try:
                    self.mail_alert(alert, self.html_template)
                except Exception as err:
                    logger.exception("Unknown exception occurred: " + str(err))
                    continue
            del alert
            queue_size = self.alert_queue.qsize()
            if queue_size > 0:
                logger.debug('Remaining events in alert queue ({})'.format(queue_size))
