import threading
import time
import random
import enum
import logging
import requests
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

from ics.system import NodeSystem
from ics.cluster_config import ClusterConfig


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
        self.log: List[dict] = []

        # Volatile state
        self.commit_index = -1  # Index of the highest log entry known to be committed
        self.last_applied = -1  # Last applied log index

        # Leader state
        self.peer_next_index: Dict[str, int] = {peer: 0 for peer in peers} # Next log entry to send to peer
        self.peer_match_index: Dict[str, int] = {peer: -1 for peer in peers}  # Highest index known to be replicated on the peer

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
                "next_index": self.peer_next_index,
                "match_index": self.peer_match_index
            }

    def _reset_election_timeout(self) -> float:
        timeout = random.uniform(5.0, 9.0)
        logger.debug(f"{self.node_id}: Reset election timeout to {timeout:.2f} seconds")
        return time.time() + timeout

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

        # Reset the peer next_index values to the index just after the last one in its log
        for peer in self.peers:
            self.peer_next_index[peer] = max(0, len(self.log) - 1)  # Set peer next index to resend last log
            self.peer_match_index[peer] = -1
        self._send_heartbeats()

    def handle_request_vote(self, term: int, candidate_id: str, last_log_index: int, last_log_term: int) -> dict:
        with self.lock:
            vote_granted = False

            # Reject vote if given term is stale
            if term < self.current_term:
                logger.debug(
                    f"{self.node_id}: Rejected vote request from {candidate_id} (stale term {term} < current {self.current_term})")
                return {
                    "term": self.current_term,
                    "vote_granted": False
                }

            # Step down if term is newer
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

            # Reset election timer if vote granted to reduce unnecessary elections
            if vote_granted:
                self.election_timeout = self._reset_election_timeout()

            return {
                "term": self.current_term,
                "vote_granted": vote_granted
            }

    def _send_heartbeats(self):
        logger.debug(f"{self.node_id}: Sending heartbeats or log entries to peers")

        for peer in self.peers:

            # If peer is missing from known index list, assume the peer is not up-to-date
            if peer not in self.peer_next_index:
                logger.warning(f"{self.node_id}: No known next index for peer {peer}, assuming zero")
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
                logger.info(f"{self.node_id}: Peer {peer} is behind, sending {entry_count} log entries starting from index {next_index}")

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
                    timeout=1.0
                )
                if response.status_code == 200:
                    result = response.json()
                    if result.get("success"):
                        if entries:
                            self.peer_match_index[peer] = next_index + len(entries) - 1
                            self.peer_next_index[peer] = self.peer_match_index[peer] + 1
                            logger.info(f"{self.node_id}: Updated match_index for {peer} to {self.peer_match_index[peer]}")
                    else:
                        self.peer_next_index[peer] = max(0, self.peer_next_index[peer] - 1)
                        logger.warning(
                            f"{self.node_id}: AppendEntries failed for {peer}, backtracking next_index to {self.peer_next_index[peer]}")
                else:
                    logger.warning(f"{self.node_id}: AppendEntries to {peer} failed with status {response.status_code}")
            except Exception as e:
                logger.warning(f"{self.node_id}: Failed to contact {peer}: {e}")

        # Update leader commit index if the majority of nodes have been updated
        match_indexes = list(self.peer_match_index.values()) + [len(self.log) - 1]  # include leader itself
        match_indexes.sort(reverse=True)
        majority_index = match_indexes[len(match_indexes) // 2] # Retrieve the median index value from all nodes

        # Only advance commit_index for entries from the current term
        if majority_index > self.commit_index and self.log[majority_index]['term'] == self.current_term:
            self.commit_index = majority_index
            logger.info(f"{self.node_id}: Advanced commit_index to {self.commit_index}")

        self.election_timeout = self._reset_election_timeout()

    def handle_append_entries(self, term: int, leader_id: str, prev_log_index: int, prev_log_term: int,
                              entries: List[dict], leader_commit: int) -> dict:
        with self.lock:

            entries_length = len(entries)
            logger.debug(f"Received {entries_length} new entries from leader {leader_id}")

            success = False
            if term >= self.current_term:
                if self.current_term != term:
                    logger.info(f"{self.node_id}: Updating to new term {term} from leader {leader_id}")
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
                    logger.debug(f"{self.node_id}: AppendEntries successful from leader {leader_id}")
                else:
                    logger.debug(f"{self.node_id}: AppendEntries log mismatch from leader {leader_id}")
            else:
                logger.debug(f"{self.node_id}: Rejected AppendEntries from {leader_id} due to stale term")

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
            logger.info(f"{self.node_id}: Appended new entry at index {index}: {entry}")

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
                        logger.warning(f"{self.node_id}: Commit index {latest_index} exceeds log length {len(self.log)} skipping apply")
                        continue

                    entry = self.log[latest_index]
                    self._apply_entry(entry)
                    self.last_applied = latest_index

    def _apply_entry(self, entry: dict):
        cmd = entry["command"]
        cmd_type = cmd.get("type")
        cmd_data = cmd.get("data")

        logger.info(f"{self.node_id}: Applying log entry at index {self.commit_index}: {cmd_type}")

        if cmd_type == "CONFIG_UPDATE":
            if not self.system:
                logger.warning(f"{self.node_id}: CONFIG_UPDATE committed but no NodeSystem bound; skipping")
                return

            try:
                self.system.update_config(cmd_data)
                logger.info(f"{self.node_id}: CONFIG_UPDATE applied")
            except Exception:
                logger.exception(f"{self.node_id}: CONFIG_UPDATE apply failed")


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

    def stop(self):
        with self.lock:
            self.running = False
        if self.thread:
            self.thread.join()
        if self.applier_thread:
            self.applier_thread.join()
