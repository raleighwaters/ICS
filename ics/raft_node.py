import threading
import time
import random
import enum
import logging
import requests
import socket
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

from ics.system import NodeSystem
from ics.cluster_config import ClusterConfig, NodeSpec
from ics.settings import settings


class RaftRole(enum.Enum):
    FOLLOWER = 'Follower'
    CANDIDATE = 'Candidate'
    LEADER = 'Leader'


class RaftNode:

    MULTICAST_GROUP = '224.0.0.1'  # Multicast group (change as needed)
    MULTICAST_PORT = 50000         # Port for discovery
    DISCOVERY_INTERVAL = 5.0       # Send a presence announcement every 5 seconds

    def __init__(self, local_node: NodeSpec, peers: List[NodeSpec], system: Optional[NodeSystem] = None):
        self.local_node = local_node
        self.peers = peers  # List of remote Nodes

        self.system = system

        self.leader_id = None

        # Raft persistent state
        self.current_term = 0
        self.voted_for: Optional[NodeSpec] = None
        self.log: List[dict] = []

        # Volatile state
        self.commit_index = -1  # Index of the highest log entry known to be committed
        self.last_applied = -1  # Last applied log index

        # Leader state
        self.peer_next_index: Dict[NodeSpec, int] = {peer: 0 for peer in peers} # Next log entry to send to peer
        self.peer_match_index: Dict[NodeSpec, int] = {peer: -1 for peer in peers}  # Highest index known to be replicated on the peer

        # Election state
        self.role = RaftRole.FOLLOWER
        self.election_timeout = self._reset_election_timeout()
        self.heartbeat_interval = 2.0  # Leader heartbeat interval (sec)

        self.lock = threading.Lock()
        self.running = False
        self.thread: Optional[threading.Thread] = None

        self.applier_thread: Optional[threading.Thread] = None

        # Auto discovery
        self.discovery_peers: List[NodeSpec] = []
        self.run_discovery = False
        self.discovery_thread: Optional[threading.Thread] = None

    def nodes(self) -> list[NodeSpec]:
        """Returns a list of all node IDs in the cluster, including self."""
        return self.peers + [self.local_node]

    def get_node(self, hostname: str):
        """
        Retrieve a Node by its hostname.

        Args:
            hostname (str): The hostname to search for.

        Raises:
            NodeNotFoundError: If no Node is found with the given hostname.

        Returns:
            Node: The Node object with the given hostname.
        """
        for node in self.nodes():
            if node.hostname == hostname:
                return node

        raise ValueError(f"Node with hostname '{hostname}' not found.")

    def get_status(self):
        with self.lock:
            return {
                "node_id": self.local_node.node_id,
                "role": self.role.value,
                "term": self.current_term,
                "log_length": len(self.log),
                "commit_index": self.commit_index,
                "last_applied": self.last_applied,
                "next_index": self.peer_next_index,
                "match_index": self.peer_match_index
            }

    def is_leader(self) -> bool:
        if self.role == RaftRole.LEADER:
            return True
        else:
            return False

    def get_leader_node(self) -> Optional[NodeSpec]:
        with self.lock:
            # If this node is the leader, return its own details
            if self.is_leader():
                return self.local_node

            # If a leader has been updated by AppendEntries RPC, fetch it
            if self.leader_id:
                for peer in self.peers:
                    if peer.node_id == self.leader_id:
                        return peer

        return None

    # def add_cluster_node(self, node: NodeSpec):
    #     config = self.get_latest_config()
    #     config.add_node(node)
    #     self.propose_new_config(config)
    #
    # def remove_cluster_node(self, name: str):
    #     config = self.get_latest_config()
    #     config.delete_node(name)
    #     self.propose_new_config(config)

    def _reset_election_timeout(self) -> float:
        timeout = random.uniform(5.0, 9.0)
        logger.debug(f"{self.local_node}: Reset election timeout to {timeout:.2f} seconds")
        return time.time() + timeout

    def _start_election(self):
        self.role = RaftRole.CANDIDATE
        self.current_term += 1
        self.voted_for = self.local_node
        votes_received = 1  # Vote for self
        logger.info(f"{self.local_node}: Starting election for term {self.current_term}")

        for peer in self.peers:
            try:
                response = requests.post(
                    f"http://{peer}/raft/request_vote",
                    json={
                        "term": self.current_term,
                        "candidate_id": self.local_node.node_id,
                        "last_log_index": len(self.log) - 1,
                        "last_log_term": self.log[-1]['term'] if self.log else 0,
                    },
                    timeout=1.0
                )
                if response.status_code == 200:
                    result = response.json()
                    if result.get("vote_granted"):
                        logger.info(f"{self.local_node}: Received vote from {peer}")
                        votes_received += 1
                    else:
                        logger.info(f"{self.local_node}: Vote from {peer} denied")
            except Exception as e:
                logger.warning(f"{self.local_node}: Failed to request vote from {peer}: {e}")

        if votes_received > (len(self.peers) + 1) // 2:
            self._become_leader()
        else:
            logger.info(f"{self.local_node}: Election failed with {votes_received} votes")
            self.role = RaftRole.FOLLOWER
            self.voted_for = None
            self.election_timeout = self._reset_election_timeout()

    def _become_leader(self):
        self.role = RaftRole.LEADER
        logger.info(f"{self.local_node}: Became leader for term {self.current_term}")

        # Reset the peer next_index values to the index just after the last one in its log
        for peer in self.peers:
            self.peer_next_index[peer] = max(0, len(self.log) - 1)  # Set peer next index to resend last log
            self.peer_match_index[peer] = -1
        self._send_heartbeats()

    def handle_request_vote(self, term: int, candidate_node: NodeSpec, last_log_index: int, last_log_term: int) -> dict:
        with self.lock:
            vote_granted = False

            # Reject vote if given term is stale
            if term < self.current_term:
                logger.debug(
                    f"{self.local_node}: Rejected vote request from {candidate_node} (stale term {term} < current {self.current_term})")
                return {
                    "term": self.current_term,
                    "vote_granted": False
                }

            # Step down if term is newer
            if term > self.current_term:
                logger.info(f"{self.local_node}: Newer term {term} detected from {candidate_node}, stepping down")
                self.current_term = term
                self.voted_for = None
                self.role = RaftRole.FOLLOWER

            if term == self.current_term and (self.voted_for is None or self.voted_for == candidate_node):
                local_last_term = self.log[-1]['term'] if self.log else 0
                local_last_index = len(self.log) - 1
                if last_log_term > local_last_term or (
                    last_log_term == local_last_term and last_log_index >= local_last_index
                ):
                    self.voted_for = candidate_node
                    vote_granted = True
                    logger.info(f"{self.local_node}: Voted for {candidate_node} in term {term}")
                else:
                    logger.info(f"{self.local_node}: Did not vote for {candidate_node} due to log inconsistency")

            # Reset election timer if vote granted to reduce unnecessary elections
            if vote_granted:
                self.election_timeout = self._reset_election_timeout()

            return {
                "term": self.current_term,
                "vote_granted": vote_granted
            }

    def _send_heartbeats(self):
        logger.debug(f"{self.local_node}: Sending heartbeats or log entries to peers")

        for peer in self.peers:

            # If peer is missing from known index list, assume the peer is not up-to-date
            if peer not in self.peer_next_index:
                logger.warning(f"{self.local_node}: No known next index for peer {peer}, assuming zero")
                self.peer_next_index[peer] = 0

            next_index = self.peer_next_index.get(peer)
            prev_index = next_index - 1
            prev_term = self.log[prev_index]['term'] if prev_index >= 0 else 0

            # If follower is up to date, send heartbeat
            if next_index >= len(self.log):
                entries = []
            else:
                # Follower is behind send real entries
                entries = self.log[next_index:]
                entry_count = len(entries)
                logger.info(f"{self.local_node}: Peer {peer} is behind, sending {entry_count} log entries starting from index {next_index}")

            try:
                response = requests.post(
                    f"http://{peer}/raft/append_entries",
                    json={
                        "term": self.current_term,
                        "leader_id": self.local_node.node_id,
                        "prev_log_index": prev_index,
                        "prev_log_term": prev_term,
                        "entries": entries,
                        "leader_commit": self.commit_index
                    },
                    timeout=1.0
                )
                if response.status_code == 200:
                    result = response.json()
                    if result.get("success"):
                        if entries:
                            self.peer_match_index[peer] = next_index + len(entries) - 1
                            self.peer_next_index[peer] = self.peer_match_index[peer] + 1
                            logger.info(f"{self.local_node}: Updated match_index for {peer} to {self.peer_match_index[peer]}")
                    else:
                        self.peer_next_index[peer] = max(0, self.peer_next_index[peer] - 1)
                        logger.warning(
                            f"{self.local_node}: AppendEntries failed for {peer}, backtracking next_index to {self.peer_next_index[peer]}")
                else:
                    logger.warning(f"{self.local_node}: AppendEntries to {peer} failed with status {response.status_code}")
            except Exception as e:
                logger.warning(f"{self.local_node}: Failed to contact {peer}: {e}")

        # Update leader commit index if the majority of nodes have been updated
        match_indexes = list(self.peer_match_index.values()) + [len(self.log) - 1]  # include leader itself
        match_indexes.sort(reverse=True)
        majority_index = match_indexes[len(match_indexes) // 2] # Retrieve the median index value from all nodes

        # Only advance commit_index for entries from the current term
        if majority_index > self.commit_index and self.log[majority_index]['term'] == self.current_term:
            self.commit_index = majority_index
            logger.info(f"{self.local_node}: Advanced commit_index to {self.commit_index}")

        self.election_timeout = self._reset_election_timeout()

    def handle_append_entries(self, term: int, leader_id: str, prev_log_index: int, prev_log_term: int,
                              entries: List[dict], leader_commit: int) -> dict:
        with self.lock:

            entries_length = len(entries)
            logger.debug(f"Received {entries_length} new entries from leader {leader_id}")

            if leader_id:
                self.leader_id = leader_id

            success = False
            if term >= self.current_term:
                if self.current_term != term:
                    logger.info(f"{self.local_node}: Updating to new term {term} from leader {leader_id}")
                self.current_term = term
                self.role = RaftRole.FOLLOWER
                self.voted_for = None
                self.election_timeout = self._reset_election_timeout()

                logger.debug(f"prev_log_index: {prev_log_index}")
                if prev_log_index == -1 or (
                    prev_log_index < len(self.log) and self.log[prev_log_index]['term'] == prev_log_term
                ):
                    for i, entry in enumerate(entries):
                        log_index = prev_log_index + 1 + i
                        if log_index < len(self.log):
                            if self.log[log_index]['term'] != entry['term']:
                                self.log = self.log[:log_index]
                                self.log.extend(entries[i:])
                                break
                        else:
                            self.log.append(entry)

                    if leader_commit > self.commit_index:
                        self.commit_index = min(leader_commit, len(self.log) - 1)
                    success = True
                    logger.debug(f"{self.local_node}: AppendEntries successful from leader {leader_id}")
                else:
                    logger.debug(f"{self.local_node}: AppendEntries log mismatch from leader {leader_id}")
            else:
                logger.debug(f"{self.local_node}: Rejected AppendEntries from {leader_id} due to stale term")

            # Return if appending the entry was successful or not
            return {
                "term": self.current_term,
                "success": success
            }

    def append_entry(self, command: dict):
        with self.lock:
            if self.role != RaftRole.LEADER:
                raise RuntimeError("Only the leader can append entries")

            entry = {"term": self.current_term, "command": command}
            self.log.append(entry)
            index = len(self.log) - 1
            logger.info(f"{self.local_node}: Appended new entry at index {index}: {entry}")

    def get_latest_config(self) -> ClusterConfig:
        with self.lock:
            for entry in reversed(self.log):
                if entry.get("command", {}).get("type") == "CONFIG_UPDATE":
                    return ClusterConfig(**entry["command"]["data"])
        logger.warning("No CONFIG_UPDATE found in log, returning empty config")
        return ClusterConfig()

    def propose_new_config(self, config: ClusterConfig):
        logger.info("Proposing new config change")
        if self.role != RaftRole.LEADER:
            raise RuntimeError("Only the leader can propose new configs")
        entry = {
            "type": "CONFIG_UPDATE",
            "data": config.model_dump()
        }
        self.append_entry(entry)

    def _apply_committed_entries(self):
        while self.running:
            time.sleep(0.1)
            with self.lock:
                if self.last_applied < self.commit_index:
                    latest_index = self.commit_index # Only apply the latest commit log entry

                    # Sanity check to avoid index error
                    if latest_index >= len(self.log):
                        logger.warning(f"{self.local_node}: Commit index {latest_index} exceeds log length {len(self.log)} skipping apply")
                        continue

                    entry = self.log[latest_index]
                    self._apply_entry(entry)
                    self.last_applied = latest_index

    def _apply_entry(self, entry: dict):
        cmd = entry["command"]
        cmd_type = cmd.get("type")
        cmd_data = cmd.get("data")

        logger.info(f"{self.local_node}: Applying log entry at index {self.commit_index}: {cmd_type}")

        if cmd_type == "CONFIG_UPDATE":
            if not self.system:
                logger.warning(f"{self.local_node}: CONFIG_UPDATE committed but no NodeSystem bound; skipping")
                return

            try:
                self.system.update_config(cmd_data)
                logger.info(f"{self.local_node}: CONFIG_UPDATE applied")
            except Exception:
                logger.exception(f"{self.local_node}: CONFIG_UPDATE apply failed")


    def _run(self):
        while self.running:
            time.sleep(0.1)
            with self.lock:
                now = time.time()

                if self.role == RaftRole.LEADER:
                    logger.debug(f"{self.local_node}: Running as leader in term {self.current_term}")
                    self._send_heartbeats()
                elif now >= self.election_timeout:
                    logger.info(f"{self.local_node}: Election timeout reached, starting election")
                    self._start_election()

    def announce_presence(self):
        """Periodically announces this node's presence via multicast."""
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as sock:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)

            # Construct the broadcast message
            cluster_name = settings.cluster_name
            node_identifier = f"{self.local_node.node_id}"
            message = f"{cluster_name}|{node_identifier}".encode("utf-8")

            while self.run_discovery:
                try:
                    sock.sendto(message, (self.MULTICAST_GROUP, self.MULTICAST_PORT))
                    logger.debug(f"{self.local_node}: Announced presence to multicast group {self.MULTICAST_GROUP}")
                except Exception as e:
                    logger.error(f"{self.local_node}: Failed to announce presence: {e}")
                time.sleep(self.DISCOVERY_INTERVAL)

    def listen_for_discovery(self):
        """Listens for announcements from other nodes and dynamically adds them."""
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", self.MULTICAST_PORT))
            group = socket.inet_aton(self.MULTICAST_GROUP)
            mreq = group + socket.inet_aton("0.0.0.0")
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

            while self.run_discovery:
                try:
                    data, _ = sock.recvfrom(1024)
                    message = data.decode("utf-8")
                    logger.debug(f"Received multicast message: {message}")

                    # Parse the cluster_name and node_id
                    cluster_name, node_id = message.split("|", 1)

                    # Ensure the cluster name matches
                    if cluster_name != settings.cluster_name:
                        logger.debug(f"{self.local_node}: Ignored message from different cluster: {cluster_name}")
                        continue

                    # Process the discovered node
                    discovered_node = NodeSpec.from_string(node_id)
                    if discovered_node != self.local_node:
                        with self.lock:
                            if discovered_node not in self.discovery_peers:
                                self.discovery_peers.append(discovered_node)
                                logger.info(f"{self.local_node}: Discovered and added new peer {discovered_node}")
                except Exception as e:
                    logger.error(f"{self.local_node}: Failed to process discovery message: {e}")

    def _discovery_loop(self):
        """Run both announce_presence and listen_for_discovery concurrently."""
        announce_thread = threading.Thread(target=self.announce_presence, daemon=True)
        listen_thread = threading.Thread(target=self.listen_for_discovery, daemon=True)
        announce_thread.start()
        listen_thread.start()
        announce_thread.join()
        listen_thread.join()

    def start_discovery(self):
        """Starts the node discovery mechanism, both announcing and listening."""
        self.run_discovery = True
        self.discovery_thread = threading.Thread(target=self._discovery_loop, daemon=True)
        self.discovery_thread.start()
        logger.info(f"{self.local_node}: Started node discovery")

    def stop_discovery(self):
        """Stops the node discovery mechanism."""
        self.run_discovery = False
        if self.discovery_thread:
            self.discovery_thread.join()
        logger.info(f"{self.local_node}: Stopped node discovery")

    def start(self):
        with self.lock:
            if not self.running:
                self.running = True
                self.thread = threading.Thread(target=self._run, name=f"raft-{self.local_node}", daemon=True)
                self.thread.start()

                self.applier_thread = threading.Thread(
                    target=self._apply_committed_entries,
                    name=f"raft-applier-{self.local_node}",
                    daemon=True
                )
                self.applier_thread.start()

                # self.start_discovery()

                logger.info(f"{self.local_node}: Raft node started")

    def stop(self):
        with self.lock:
            self.running = False
        if self.thread:
            self.thread.join()
        if self.applier_thread:
            self.applier_thread.join()

        # self.stop_discovery()
