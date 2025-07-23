import threading
import time
import random
import enum
import logging
import requests
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

class RaftRole(enum.Enum):
    FOLLOWER = 'Follower'
    CANDIDATE = 'Candidate'
    LEADER = 'Leader'

class RaftNode:
    def __init__(self, node_id: str, peers: List[str]):
        self.node_id = node_id
        self.peers = peers  # List of other node IDs (IP:port)

        # Raft persistent state
        self.current_term = 0
        self.voted_for: Optional[str] = None
        self.log: List[dict] = []  # Will hold commands

        # Volatile state
        self.commit_index = 0
        self.last_applied = 0

        # Leader state
        self.next_index: Dict[str, int] = {}
        self.match_index: Dict[str, int] = {}

        # Election state
        self.role = RaftRole.FOLLOWER
        self.election_timeout = self._reset_election_timeout()
        self.heartbeat_interval = 2.0  # Leader heartbeat interval (sec)

        self.lock = threading.Lock()
        self.running = False
        self.thread: Optional[threading.Thread] = None

    def _reset_election_timeout(self) -> float:
        return time.time() + random.uniform(5.0, 9.0)

    def _run(self):
        while self.running:
            time.sleep(0.1)
            with self.lock:
                now = time.time()

                if self.role == RaftRole.LEADER:
                    self._send_heartbeats()
                elif now >= self.election_timeout:
                    self._start_election()

    def start(self):
        with self.lock:
            if not self.running:
                self.running = True
                self.thread = threading.Thread(target=self._run, name=f"raft-{self.node_id}", daemon=True)
                self.thread.start()

    def _send_heartbeats(self):
        logger.debug(f"{self.node_id}: Sending heartbeats to peers")
        for peer in self.peers:
            try:
                response = requests.post(
                    f"http://{peer}/raft/append_entries",
                    json={
                        "term": self.current_term,
                        "leader_id": self.node_id,
                        "prev_log_index": len(self.log) - 1,
                        "prev_log_term": self.log[-1]['term'] if self.log else 0,
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
                        votes_received += 1
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

            return {
                "term": self.current_term,
                "vote_granted": vote_granted
            }

    def handle_append_entries(self, term: int, leader_id: str, prev_log_index: int, prev_log_term: int,
                              entries: List[dict], leader_commit: int) -> dict:
        with self.lock:
            success = False
            if term >= self.current_term:
                self.current_term = term
                self.role = RaftRole.FOLLOWER
                self.voted_for = None
                self.election_timeout = self._reset_election_timeout()

                # Check log consistency
                if prev_log_index == -1 or (
                    prev_log_index < len(self.log) and self.log[prev_log_index]['term'] == prev_log_term
                ):
                    # Append any new entries (simplified: we assume no conflicts)
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

            return {
                "term": self.current_term,
                "success": success
            }

    def stop(self):
        with self.lock:
            self.running = False
        if self.thread:
            self.thread.join()