"""Algorithm correctness tests, anchored on the spec's own example."""

from django.test import SimpleTestCase

from . import graph

# The example from the spec.
SPEC_ROUTES = [
    ["A", "B", "C", "D"],
    ["C", "M", "N", "G", "E", "R"],
    ["E", "J", "K", "L", "A"],
]


class KShortestPathsTests(SimpleTestCase):
    def setUp(self):
        self.adj = graph.build_adjacency(SPEC_ROUTES)

    def test_spec_example_k_to_m(self):
        # Spec: getting from K to M must follow [K, J, E, G, N, M].
        paths = graph.k_shortest_paths(self.adj, "K", "M", k=3)
        self.assertTrue(paths)
        self.assertEqual(paths[0], ["K", "J", "E", "G", "N", "M"])

    def test_results_are_shortest_first(self):
        paths = graph.k_shortest_paths(self.adj, "A", "R", k=3)
        lengths = [len(p) for p in paths]
        self.assertEqual(lengths, sorted(lengths))

    def test_at_most_k_distinct_paths(self):
        paths = graph.k_shortest_paths(self.adj, "A", "R", k=3)
        self.assertLessEqual(len(paths), 3)
        unique = {tuple(p) for p in paths}
        self.assertEqual(len(unique), len(paths))

    def test_all_paths_are_simple(self):
        for p in graph.k_shortest_paths(self.adj, "A", "R", k=3):
            self.assertEqual(len(p), len(set(p)))

    def test_same_start_and_end(self):
        self.assertEqual(graph.k_shortest_paths(self.adj, "A", "A"), [["A"]])

    def test_unknown_node_returns_empty(self):
        self.assertEqual(graph.k_shortest_paths(self.adj, "A", "ZZZ"), [])

    def test_no_connection_returns_empty(self):
        # Two disjoint components -> no path between them.
        adj = graph.build_adjacency([["X", "Y"], ["P", "Q"]])
        self.assertEqual(graph.k_shortest_paths(adj, "X", "Q"), [])


class WaypointTests(SimpleTestCase):
    """Required intermediate stops: real-world simple paths, no pointless detour."""

    def setUp(self):
        # A-B direct; A-C and C-B direct (short way through C); plus a long
        # detour from A to C via Z, X, N, K.
        self.adj = graph.build_adjacency(
            [["A", "B"], ["A", "C"], ["C", "B"], ["A", "Z", "X", "N", "K", "C"]]
        )

    def test_route_passes_through_required_stop(self):
        for p in graph.k_shortest_paths(self.adj, "A", "B", via=["C"]):
            self.assertIn("C", p)

    def test_no_revisits_with_waypoints(self):
        for p in graph.k_shortest_paths(self.adj, "A", "B", via=["C"]):
            self.assertEqual(len(p), len(set(p)), f"route revisits a node: {p}")

    def test_short_connection_is_not_detoured(self):
        # The short A-C-B must be chosen; the long A-Z-X-N-K-C-B detour rejected.
        paths = graph.k_shortest_paths(self.adj, "A", "B", via=["C"])
        self.assertEqual(paths[0], ["A", "C", "B"])
        self.assertNotIn(["A", "Z", "X", "N", "K", "C", "B"], paths)

    def test_optimised_stop_order(self):
        # Stops given as [X, A] are visited in the order that minimises the
        # route: A before X (A sits between the start K... here start=A).
        adj = graph.build_adjacency([["S", "P", "Q", "E"]])
        paths = graph.k_shortest_paths(adj, "S", "E", via=["Q", "P"])
        self.assertEqual(paths[0], ["S", "P", "Q", "E"])

    def test_unknown_stop_returns_empty(self):
        self.assertEqual(graph.k_shortest_paths(self.adj, "A", "B", via=["ZZZ"]), [])

    def test_stop_equal_to_endpoint_is_ignored(self):
        # A required stop that is already the start/end changes nothing.
        with_stop = graph.k_shortest_paths(self.adj, "A", "B", via=["A"])
        plain = graph.k_shortest_paths(self.adj, "A", "B")
        self.assertEqual(with_stop, plain)

    def test_empty_via_matches_no_via(self):
        self.assertEqual(
            graph.k_shortest_paths(self.adj, "A", "B", via=[]),
            graph.k_shortest_paths(self.adj, "A", "B"),
        )


class GraphShapeTests(SimpleTestCase):
    def test_edges_are_bidirectional(self):
        adj = graph.build_adjacency([["X", "Y", "Z"]])
        self.assertIn("Y", adj["X"])
        self.assertIn("X", adj["Y"])
        self.assertIn("Z", adj["Y"])
        self.assertIn("Y", adj["Z"])

    def test_network_dedupes_undirected_links(self):
        adj = graph.build_adjacency([["X", "Y"]])
        net = graph.to_network(adj)
        self.assertEqual(len(net["links"]), 1)
        self.assertEqual({n["id"] for n in net["nodes"]}, {"X", "Y"})
