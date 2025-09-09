from ics.raft_node import Node


def test_node_initialization():
    node = Node("localhost", 5000)
    assert node.hostname == "localhost"
    assert node.port == 5000
    assert node.node_id == "localhost:5000"

def test_node_equality():
    node1 = Node("localhost", 5000)
    node2 = Node("localhost", 5000)
    assert node1 == node2
