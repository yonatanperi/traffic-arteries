"""Algorithm correctness tests, anchored on the spec's own example."""

from django.test import SimpleTestCase

from .graph import Graph, RouteFinder

# The example from the spec.
SPEC_ROUTES = [
    ["A", "B", "C", "D"],
    ["C", "M", "N", "G", "E", "R"],
    ["E", "J", "K", "L", "A"],
]


class KShortestPathsTests(SimpleTestCase):
    def setUp(self):
        self.finder = RouteFinder(Graph.from_routes(SPEC_ROUTES))

    def test_spec_example_k_to_m(self):
        # Spec: getting from K to M must follow [K, J, E, G, N, M].
        paths = self.finder.k_shortest_paths("K", "M", k=3)
        self.assertTrue(paths)
        self.assertEqual(paths[0], ["K", "J", "E", "G", "N", "M"])

    def test_results_are_shortest_first(self):
        paths = self.finder.k_shortest_paths("A", "R", k=3)
        lengths = [len(p) for p in paths]
        self.assertEqual(lengths, sorted(lengths))

    def test_at_most_k_distinct_paths(self):
        paths = self.finder.k_shortest_paths("A", "R", k=3)
        self.assertLessEqual(len(paths), 3)
        unique = {tuple(p) for p in paths}
        self.assertEqual(len(unique), len(paths))

    def test_all_paths_are_simple(self):
        for p in self.finder.k_shortest_paths("A", "R", k=3):
            self.assertEqual(len(p), len(set(p)))

    def test_same_start_and_end(self):
        self.assertEqual(self.finder.k_shortest_paths("A", "A"), [["A"]])

    def test_unknown_node_returns_empty(self):
        self.assertEqual(self.finder.k_shortest_paths("A", "ZZZ"), [])

    def test_no_connection_returns_empty(self):
        # Two disjoint components -> no path between them.
        finder = RouteFinder(Graph.from_routes([["X", "Y"], ["P", "Q"]]))
        self.assertEqual(finder.k_shortest_paths("X", "Q"), [])


class WaypointTests(SimpleTestCase):
    """Required intermediate stops: real-world simple paths, no pointless detour."""

    def setUp(self):
        # A-B direct; A-C and C-B direct (short way through C); plus a long
        # detour from A to C via Z, X, N, K.
        self.finder = RouteFinder(
            Graph.from_routes(
                [["A", "B"], ["A", "C"], ["C", "B"], ["A", "Z", "X", "N", "K", "C"]]
            )
        )

    def test_route_passes_through_required_stop(self):
        for p in self.finder.k_shortest_paths("A", "B", via=["C"]):
            self.assertIn("C", p)

    def test_no_revisits_with_waypoints(self):
        for p in self.finder.k_shortest_paths("A", "B", via=["C"]):
            self.assertEqual(len(p), len(set(p)), f"route revisits a node: {p}")

    def test_short_connection_is_not_detoured(self):
        # The short A-C-B must be chosen; the long A-Z-X-N-K-C-B detour rejected.
        paths = self.finder.k_shortest_paths("A", "B", via=["C"])
        self.assertEqual(paths[0], ["A", "C", "B"])
        self.assertNotIn(["A", "Z", "X", "N", "K", "C", "B"], paths)

    def test_optimised_stop_order(self):
        # Stops given as [Q, P] are visited in the order that minimises the
        # route: P before Q along the chain S-P-Q-E.
        finder = RouteFinder(Graph.from_routes([["S", "P", "Q", "E"]]))
        paths = finder.k_shortest_paths("S", "E", via=["Q", "P"])
        self.assertEqual(paths[0], ["S", "P", "Q", "E"])

    def test_unknown_stop_returns_empty(self):
        self.assertEqual(self.finder.k_shortest_paths("A", "B", via=["ZZZ"]), [])

    def test_stop_equal_to_endpoint_is_ignored(self):
        # A required stop that is already the start/end changes nothing.
        with_stop = self.finder.k_shortest_paths("A", "B", via=["A"])
        plain = self.finder.k_shortest_paths("A", "B")
        self.assertEqual(with_stop, plain)

    def test_empty_via_matches_no_via(self):
        self.assertEqual(
            self.finder.k_shortest_paths("A", "B", via=[]),
            self.finder.k_shortest_paths("A", "B"),
        )


class GraphShapeTests(SimpleTestCase):
    def test_edges_are_bidirectional(self):
        graph = Graph.from_routes([["X", "Y", "Z"]])
        self.assertIn("Y", graph.neighbors("X"))
        self.assertIn("X", graph.neighbors("Y"))
        self.assertIn("Z", graph.neighbors("Y"))
        self.assertIn("Y", graph.neighbors("Z"))

    def test_network_dedupes_undirected_links(self):
        graph = Graph.from_routes([["X", "Y"]])
        net = graph.to_network()
        self.assertEqual(len(net["links"]), 1)
        self.assertEqual({n["id"] for n in net["nodes"]}, {"X", "Y"})
