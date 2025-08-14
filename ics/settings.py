import logging
import os
import yaml
from typing import List, Optional
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path("/etc/ics/config.yaml")
DEFAULT_ENV_FILE = Path(".env")

class ICSSettings(BaseSettings):

    model_config = SettingsConfigDict(
        env_prefix="ICS_",
        case_sensitive=False,
        env_file=DEFAULT_ENV_FILE,
        extra="ignore",
    )

    hostname: str = Field(default_factory=lambda: os.uname()[1])

    var_dir: Path = Field("/var/opt/ics")
    log_dir: Path = Field("/var/opt/ics/log")
    conf_dir: Path = Field("/var/opt/ics/config")
    uds_dir: Path = Field("/var/opt/ics/uds")

    daemon_port: int = Field(9090)
    engine_port: int = Field(9091)
    alert_port: int = Field(9092)
    api_port: int = Field(5000)

    alert_recipients: Optional[List[str]] = None
    peers: Optional[List[str]] = None
    alert_level: str = Field("NOTSET")

    group_limit: int = Field(200)
    resource_limit: int = Field(5000)

    # Derived fields
    cluster_name: Optional[str] = None
    conf_file: Optional[Path] = None
    uds_file: Optional[Path] = None
    alert_log: Optional[Path] = None
    res_log: Optional[Path] = None

    # Compute derived fields
    def model_post_init(self, __context):
        self.conf_file = self.conf_dir / "main.cf"
        self.uds_file = self.uds_dir / "uds_socket"
        self.alert_log = self.log_dir / "alerts.log"
        self.res_log = self.log_dir / "resource.log"
        self.cluster_name = self.hostname  # Temporary

    @classmethod
    def load(cls) -> "ICSSettings":
        config_data = {}

        # Load from YAML if it exists
        if DEFAULT_CONFIG_PATH.exists():
            with open(DEFAULT_CONFIG_PATH, "r") as f:
                config_data = yaml.safe_load(f) or {}

        # Allow environment to override any values
        return cls(**config_data)

    def log_settings(self):
        logger.info("Application settings:")
        for key, value in self.model_dump().items():
            logger.info(f"   {key} = {value}")

        if not self.alert_recipients:
            logger.warning("ICS alert recipients are not configured! No alerts will be sent.")

    def load_from_file(self, config_file: str):

        path = Path(config_file)

        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(path, "r") as f:
            config_data = yaml.safe_load(f) or {}

        for key, value in config_data.items():
            if hasattr(self, key):
                setattr(self, key, value)
            else:
                logger.warning(f"Ignored unknown setting '{key}' in {path}")

        self.model_post_init(None)
        logger.info(f"Settings reloaded from {path}")


settings = ICSSettings.load()
