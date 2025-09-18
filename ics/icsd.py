import argparse
import logging
import uvicorn
import socket
import threading
import sys

import Pyro4 as Pyro

from ics.settings import settings
from ics.api import create_api
from ics.logging_config import setup_logging
from ics.models import NodeSpec
from ics.raft_node import RaftNode
from ics.system import NodeSystem
from ics.alerts import AlertHandler

def start_api(raft_node, system):
    app = create_api(raft_node, system)
    uvicorn.run(app, host="0.0.0.0", port=settings.api_port, log_config=None)


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


def parse_args():
    parser = argparse.ArgumentParser(description="ICS Daemon")
    parser.add_argument("--api-port", type=int, help="Port for the API server")
    parser.add_argument("--config", type=str, help="Path to alternate config YAML file")

    return parser.parse_args()


def main():
    setup_logging()
    logger = logging.getLogger("icsd")
    logger.info("Starting ICS Daemon")
    logger.info('Python version: ' + sys.version.replace('\n', ''))

    args = parse_args()

    if args.config:
        settings.load_from_file(args.config)

    # Override settings with CLI arguments if provided
    if args.api_port:
        settings.api_port = args.api_port


    settings.log_settings()

    system = NodeSystem()

    peers = [
        NodeSpec.from_string(peer)
        for peer in settings.members
        if NodeSpec.from_string(peer).hostname != settings.hostname
    ]
    raft_node = RaftNode(NodeSpec(hostname=settings.hostname, port=settings.api_port), system=system, peers=peers)
    raft_node.start()

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
    start_api(raft_node, system)


if __name__ == "__main__":
    main()
