import os
import yaml
import logging
import logging.config

def setup_logging(default_path='./ics/config/logging.yaml', env_key='ICS_LOG_CONFIG'):
    """Setup logging configuration from YAML file."""
    path = os.getenv(env_key, default_path)
    if os.path.exists(path):
        with open(path, 'r') as f:
            config = yaml.safe_load(f)
        logging.config.dictConfig(config)
    else:
        logging.basicConfig(level=logging.INFO)
        logging.getLogger(__name__).warning(f"Logging config file not found: {path}, using basicConfig.")
