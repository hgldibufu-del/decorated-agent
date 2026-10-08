"""dw-infrastructure —— 基础设施适配器。

唯一允许持有外部 IO 的共享包：配置、日志、PostgreSQL、Redis、Kafka。
"""

from dw_infrastructure.config import Environment, Settings, get_settings
from dw_infrastructure.db import Database, DatabaseError, InfrastructureError
from dw_infrastructure.health import (
    HealthService,
    InfrastructureBundle,
    Probe,
    build_health_service,
    default_probes,
)
from dw_infrastructure.kafka import KafkaAdmin, KafkaAdminError
from dw_infrastructure.logging_setup import (
    configure_logging,
    get_logger,
    redact,
    request_id_var,
)
from dw_infrastructure.redis import RedisCache, RedisConnectionError

__version__ = "0.1.0"

__all__ = [
    "Database",
    "DatabaseError",
    "Environment",
    "HealthService",
    "InfrastructureBundle",
    "InfrastructureError",
    "KafkaAdmin",
    "KafkaAdminError",
    "Probe",
    "RedisCache",
    "RedisConnectionError",
    "Settings",
    "__version__",
    "build_health_service",
    "configure_logging",
    "default_probes",
    "get_logger",
    "get_settings",
    "redact",
    "request_id_var",
]
