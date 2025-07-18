import logging
import uvicorn
import socket
import threading
import sys

import Pyro4 as Pyro

from ics.settings import settings
from ics.api import create_api
from ics.logging_config import setup_logging
from ics.system import NodeSystem
from ics.alerts import AlertHandler


def start_api(system):
    app = create_api(system)
    uvicorn.run(app, host="0.0.0.0", port=settings.api_port)


def start_system_server(system):
    system.startup()
    Pyro.Daemon.serveSimple(
        {
            system: 'system'
        },
        port=settings.engine_port,
        host=socket.gethostname(),
        ns=False,
        verbose=False)


def start_alert_server():
    alert_handler = AlertHandler()

    # Start alert handler thread (for processing the alert queue)
    handler_thread = threading.Thread(target=alert_handler.run, name="alert-handler", daemon=True)
    handler_thread.start()

    # Expose it over Pyro
    Pyro.Daemon.serveSimple(
        {
            alert_handler: 'alert_handler'
        },
        port=settings.alert_port,
        host=socket.gethostname(),
        ns=False,
        verbose=False
    )

def main():
    setup_logging()
    logger = logging.getLogger("icsd")
    logger.info("Starting ICS Daemon")
    logger.info('Python version: ' + sys.version.replace('\n', ''))

    settings.log_settings()

    system = NodeSystem()

    # Start Pyro engine thread
    engine_thread = threading.Thread(target=start_system_server, args=(system,), daemon=True)
    engine_thread.start()
    logger.info(f"NodeSystem Pyro started on port {settings.engine_port}")

    # Start AlertServer Pyro thread
    alert_thread = threading.Thread(target=start_alert_server, daemon=True)
    alert_thread.start()
    logger.info(f"AlertServer Pyro started on port {settings.alert_port}")

    # Run FastAPI in main thread
    logger.info("FastAPI server started on port 5000")
    start_api(system)

if __name__ == "__main__":
    main()
