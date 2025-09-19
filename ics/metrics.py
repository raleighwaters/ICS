from prometheus_client import Gauge, Counter

# Raft
ics_raft_term = Gauge(
    "ics_raft_term",
    "ICS Raft Term",
    labelnames=["cluster_name"]
)
ics_raft_leader_changes_total = Counter(
    "ics_raft_leader_changes_total",
    "Total number of ICS raft leader changes",
    labelnames=["cluster_name"]
)
ics_raft_log_entries = Gauge(
    "ics_raft_log_entries",
    "Number of log entries",
    labelnames=["cluster_name"]
)
ics_raft_log_size_bytes = Gauge(
    "ics_raft_log_size_bytes",
    "Size of log entries",
    labelnames=["cluster_name"]
)

# Engine and resource lifecycle
ics_engine_queue_length = Gauge(
    "ics_engine_queue_length",
    "ICS Engine Queue Length",
    labelnames=["cluster_name"]
)
ics_resource_state = Gauge(
    "ics_resource_state",
    "ICS Resource State",
    labelnames=["resource_name", "cluster_name"]
)
ics_resource_faults_total = Counter(
    "ics_resource_faults_total",
    "ICS Resource Restarts Total",
    labelnames=["resource_name", "cluster_name"]
)

ics_group_state = Gauge(
    "ics_group_state",
    "ICS Group State",
    labelnames=["group_name", "cluster_name"]
)
