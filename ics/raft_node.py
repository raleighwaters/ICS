import threading
import time
import random
import enum
import logging
import requests
from typing import List, Dict, Optional

from ics.system import NodeSystem
from ics.cluster_config import ClusterConfig

logger = logging.getLogger(__name__)


class RaftRole(enum.Enum):
    FOLLOWER = 'Follower'
    CANDIDATE = 'Candidate'
    LEADER = 'Leader'

class RaftNode:
    def __init__(self, node_id: str, peers: List[str], system: Optional[NodeSystem] = None):
        self.node_id = node_id
        self.peers = peers  # List of other node IDs (IP:port)

        self.system = system

        # Raft persistent state
        self.current_term = 0
        self.voted_for: Optional[str] = None
        self.log: List[dict] = []  # Will hold commands

        # Volatile state
        self.commit_index = -1
        self.last_applied = -1

        # Leader state
        self.next_index: Dict[str, int] = {peer: 0 for peer in peers}
        self.match_index: Dict[str, int] = {peer: -1 for peer in peers}

        # Election state
        self.role = RaftRole.FOLLOWER
        self.election_timeout = self._reset_election_timeout()
        self.heartbeat_interval = 2.0  # Leader heartbeat interval (sec)

        self.lock = threading.Lock()
        self.running = False
        self.thread: Optional[threading.Thread] = None

        self.applier_thread: Optional[threading.Thread] = None

    def get_status(self):
        with self.lock:
            return {
                "node_id": self.node_id,
                "role": self.role.value,
                "term": self.current_term,
                "log_length": len(self.log),
                "commit_index": self.commit_index,
                "last_applied": self.last_applied,
                "next_index": self.next_index,
                "match_index": self.match_index
            }

    def _reset_election_timeout(self) -> float:
        timeout = random.uniform(5.0, 9.0)
        logger.debug(f"{self.node_id}: Reset election timeout to {timeout:.2f} seconds")
        return time.time() + timeout

    def _run(self):
        while self.running:
            time.sleep(0.1)
            with self.lock:
                now = time.time()

                if self.role == RaftRole.LEADER:
                    logger.debug(f"{self.node_id}: Running as leader in term {self.current_term}")
                    self._send_heartbeats()
                elif now >= self.election_timeout:
                    logger.info(f"{self.node_id}: Election timeout reached, starting election")
                    self._start_election()

    def start(self):
        with self.lock:
            if not self.running:
                self.running = True
                self.thread = threading.Thread(target=self._run, name=f"raft-{self.node_id}", daemon=True)
                self.thread.start()

                self.applier_thread = threading.Thread(
                    target=self._apply_committed_entries,
                    name=f"raft-applier-{self.node_id}",
                    daemon=True
                )
                self.applier_thread.start()

                logger.info(f"{self.node_id}: Raft node started")

    def _send_heartbeats(self):
        logger.debug(f"{self.node_id}: Sending heartbeats to peers")
        for peer in self.peers:
            prev_index = self.next_index.get(peer, 0) - 1
            prev_term = self.log[prev_index]['term'] if prev_index >= 0 and prev_index < len(self.log) else 0

            try:
                response = requests.post(
                    f"http://{peer}/raft/append_entries",
                    json={
                        "term": self.current_term,
                        "leader_id": self.node_id,
                        "prev_log_index": prev_index,
                        "prev_log_term": prev_term,
                        "entries": [],  # heartbeat has no log entries
                        "leader_commit": self.commit_index
                    },
                    timeout=1.0
                )
                if response.status_code != 200:
                    logger.warning(f"{self.node_id}: Heartbeat to {peer} failed with {response.status_code}")
            except Exception as e:
                logger.warning(f"{self.node_id}: Heartbeat to {peer} failed: {e}")
        self.election_timeout = self._reset_election_timeout()

    def _start_election(self):
        self.role = RaftRole.CANDIDATE
        self.current_term += 1
        self.voted_for = self.node_id
        votes_received = 1  # Vote for self
        logger.info(f"{self.node_id}: Starting election for term {self.current_term}")

        for peer in self.peers:
            try:
                response = requests.post(
                    f"http://{peer}/raft/request_vote",
                    json={
                        "term": self.current_term,
                        "candidate_id": self.node_id,
                        "last_log_index": len(self.log) - 1,
                        "last_log_term": self.log[-1]['term'] if self.log else 0,
                    },
                    timeout=1.0
                )
                if response.status_code == 200:
                    result = response.json()
                    if result.get("vote_granted"):
                        logger.info(f"{self.node_id}: Received vote from {peer}")
                        votes_received += 1
                    else:
                        logger.info(f"{self.node_id}: Vote from {peer} denied")
            except Exception as e:
                logger.warning(f"{self.node_id}: Failed to request vote from {peer}: {e}")

        if votes_received > (len(self.peers) + 1) // 2:
            self._become_leader()
        else:
            logger.info(f"{self.node_id}: Election failed with {votes_received} votes")
            self.role = RaftRole.FOLLOWER
            self.voted_for = None
            self.election_timeout = self._reset_election_timeout()

    def _become_leader(self):
        self.role = RaftRole.LEADER
        logger.info(f"{self.node_id}: Became leader for term {self.current_term}")
        for peer in self.peers:
            self.next_index[peer] = len(self.log)
            self.match_index[peer] = 0
        self._send_heartbeats()

    def handle_request_vote(self, term: int, candidate_id: str, last_log_index: int, last_log_term: int) -> dict:
        with self.lock:
            vote_granted = False
            if term > self.current_term:
                logger.info(f"{self.node_id}: Newer term {term} detected from {candidate_id}, stepping down")
                self.current_term = term
                self.voted_for = None
                self.role = RaftRole.FOLLOWER

            if term == self.current_term and (self.voted_for is None or self.voted_for == candidate_id):
                local_last_term = self.log[-1]['term'] if self.log else 0
                local_last_index = len(self.log) - 1
                if last_log_term > local_last_term or (
                    last_log_term == local_last_term and last_log_index >= local_last_index
                ):
                    self.voted_for = candidate_id
                    vote_granted = True
                    logger.info(f"{self.node_id}: Voted for {candidate_id} in term {term}")
                else:
                    logger.info(f"{self.node_id}: Did not vote for {candidate_id} due to log inconsistency")

            return {
                "term": self.current_term,
                "vote_granted": vote_granted
            }

    def handle_append_entries(self, term: int, leader_id: str, prev_log_index: int, prev_log_term: int,
                              entries: List[dict], leader_commit: int) -> dict:
        with self.lock:
            success = False
            if term >= self.current_term:
                if self.current_term != term:
                    logger.info(f"{self.node_id}: Updating to new term {term} from leader {leader_id}")
                self.current_term = term
                self.role = RaftRole.FOLLOWER
                self.voted_for = None
                self.election_timeout = self._reset_election_timeout()

                if prev_log_index == -1 or (
                    prev_log_index < len(self.log) and self.log[prev_log_index]['term'] == prev_log_term
                ):
                    for i, entry in enumerate(entries):
                        log_index = prev_log_index + 1 + i
                        if log_index >= len(self.log):
                            self.log.append(entry)
                        elif self.log[log_index]['term'] != entry['term']:
                            self.log = self.log[:log_index]
                            self.log.append(entry)

                    if leader_commit > self.commit_index:
                        self.commit_index = min(leader_commit, len(self.log) - 1)
                    success = True
                    logger.debug(f"{self.node_id}: AppendEntries successful from leader {leader_id}")
                else:
                    logger.debug(f"{self.node_id}: AppendEntries log mismatch from leader {leader_id}")
            else:
                logger.debug(f"{self.node_id}: Rejected AppendEntries from {leader_id} due to stale term")

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
            logger.info(f"{self.node_id}: Appended new entry at index {index}: {entry}")

        # Start replication in a background thread
        threading.Thread(target=self._replicate_log_entry, args=(index,), daemon=True).start()

    def _replicate_log_entry(self, index: int):
        entry = self.log[index]
        success_count = 1  # count self

        for peer in self.peers:
            next_idx = self.next_index.get(peer, len(self.log))

            while next_idx <= index:
                prev_index = next_idx - 1
                prev_term = self.log[prev_index]['term'] if prev_index >= 0 else 0
                entries = self.log[next_idx:index + 1]

                try:
                    response = requests.post(
                        f"http://{peer}/raft/append_entries",
                        json={
                            "term": self.current_term,
                            "leader_id": self.node_id,
                            "prev_log_index": prev_index,
                            "prev_log_term": prev_term,
                            "entries": entries,
                            "leader_commit": self.commit_index
                        },
                        timeout=2.0
                    )

                    if response.status_code == 200:
                        result = response.json()
                        if result.get("success"):
                            self.match_index[peer] = index
                            self.next_index[peer] = index + 1
                            success_count += 1
                            logger.info(f"{self.node_id}: Log entry replicated to {peer}")
                            break
                        else:
                            self.next_index[peer] = max(0, self.next_index[peer] - 1)
                            logger.info(
                                f"{self.node_id}: AppendEntries to {peer} failed, decrementing next_index to {self.next_index[peer]}")
                    else:
                        logger.warning(f"{self.node_id}: AppendEntries to {peer} failed with {response.status_code}")
                        break
                except Exception as e:
                    logger.warning(f"{self.node_id}: Failed to replicate to {peer}: {e}")
                    break

        with self.lock:
            if success_count > (len(self.peers) + 1) // 2:
                self.commit_index = index
                logger.info(f"{self.node_id}: Entry at index {index} committed")

    def _apply_committed_entries(self):
        while self.running:
            time.sleep(0.1)
            with self.lock:
                if self.last_applied < self.commit_index:
                    self.last_applied = self.commit_index
                    entry = self.log[self.last_applied]
                    self._apply_entry(entry)

    def _apply_entry(self, entry: dict):
        cmd = entry["command"]
        cmd_type = cmd.get("type")
        cmd_data = cmd.get("data")

        logger.info(f"{self.node_id}: Applying log entry at index {self.last_applied}: {cmd_type}")

        if cmd_type == "CONFIG_UPDATE":
            # Call system method to update resource config
            # For example: self.system.update_config(cmd_data)
            pass

        elif cmd_type == "SET_STATE":
            # Call system method to set desired state
            # For example: self.system.set_resource_state(cmd_data["resource"], cmd_data["state"])
            pass

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

    def stop(self):
        with self.lock:
            self.running = False
        if self.thread:
            self.thread.join()
        if self.applier_thread:
            self.applier_thread.join()
