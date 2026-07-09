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

    def test_results_are_best_first(self):
        # Best-first now means fewest merged routes, then fewest intersections.
        routes = self.finder.find_routes("A", "R", k=3)
        keys = [(r.route_count, r.crossroad_hops) for r in routes]
        self.assertEqual(keys, sorted(keys))

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


class TransparencyTests(SimpleTestCase):
    """Nodes with <=2 connections are transparent: only crossroads count."""

    def assert_full_chain(self, graph, path):
        """Every consecutive pair in a returned route is a real graph edge."""
        for a, b in zip(path, path[1:]):
            self.assertIn(b, graph.neighbors(a), f"{a}->{b} is not a real edge in {path}")

    def test_crossroads_are_degree_three_or_more(self):
        # C has neighbours B, D, X (degree 3); everything else is degree <= 2.
        graph = Graph.from_routes([["A", "B", "C", "D", "E"], ["C", "X"]])
        self.assertEqual(graph.crossroads(), ["C"])
        self.assertEqual(graph.degree("B"), 2)  # transparent
        self.assertEqual(graph.degree("C"), 3)  # crossroad

    def test_transparent_chain_counts_as_one_hop(self):
        # A long transparent chain A..B is ONE crossroad-to-crossroad hop, so it
        # beats the two-hop route through crossroad M -- even though it has far
        # more nodes. Under the old edge-count model M's route (2 edges) would
        # have won over the chain (6 edges); this is the shortest-path change.
        graph = Graph.from_routes(
            [
                ["A", "l1", "l2", "l3", "l4", "l5", "B"],  # long transparent road
                ["A", "M", "B"],                            # short road via crossroad M
                ["A", "a2"], ["B", "b2"], ["M", "m2"],      # make A, B, M crossroads
            ]
        )
        finder = RouteFinder(graph)
        paths = finder.k_shortest_paths("A", "B", k=3)
        self.assertEqual(paths[0], ["A", "l1", "l2", "l3", "l4", "l5", "B"])
        self.assertIn(["A", "M", "B"], paths)
        for p in paths:
            self.assert_full_chain(graph, p)

    def test_parallel_roads_are_distinct_alternatives(self):
        # A and C are crossroads joined by TWO different roads: a direct edge and
        # a road through transparent p, q. Both must come back as alternatives.
        graph = Graph.from_routes(
            [["A", "C"], ["A", "p", "q", "C"], ["A", "x"], ["C", "y"]]
        )
        paths = RouteFinder(graph).k_shortest_paths("A", "C", k=3)
        self.assertIn(["A", "C"], paths)
        self.assertIn(["A", "p", "q", "C"], paths)
        self.assertEqual(len(paths), 2)

    def test_transparent_endpoint_is_still_routable(self):
        # a2 and m2 are dead-end (degree-1) transparent nodes; as the query's
        # terminals they are kept and must remain routable through the network.
        graph = Graph.from_routes(
            [
                ["A", "l1", "l2", "l3", "l4", "l5", "B"],
                ["A", "M", "B"],
                ["A", "a2"], ["B", "b2"], ["M", "m2"],
            ]
        )
        paths = RouteFinder(graph).k_shortest_paths("a2", "m2")
        self.assertTrue(paths)
        self.assertEqual(paths[0][0], "a2")
        self.assertEqual(paths[0][-1], "m2")
        self.assert_full_chain(graph, paths[0])

    def test_transparent_only_graph_collapses_to_single_segment(self):
        # No crossroads anywhere: a plain chain is one segment end to end.
        graph = Graph.from_routes([["S", "a", "b", "c", "d", "E"]])
        paths = RouteFinder(graph).k_shortest_paths("S", "E", k=3)
        self.assertEqual(paths, [["S", "a", "b", "c", "d", "E"]])


class MergeTests(SimpleTestCase):
    """"Best" = the route merging the fewest authored routes from routes.json."""

    def setUp(self):
        self.finder = RouteFinder(Graph.from_routes(SPEC_ROUTES))

    def test_edge_route_membership(self):
        g = Graph.from_routes([["A", "B", "C"], ["B", "C", "D"]])
        self.assertEqual(g.routes_on("A", "B"), (0,))
        self.assertEqual(g.routes_on("C", "B"), (0, 1))  # order-independent; both
        self.assertEqual(g.routes_on("C", "D"), (1,))

    def test_best_merges_fewest_routes(self):
        # The spec example: A..G along one route beats A-B-R-G across two, even
        # though A-B-R-G is shorter.
        finder = RouteFinder(
            Graph.from_routes([
                ["A", "B", "C", "D", "E", "F", "G"],
                ["B", "R", "G"],
            ])
        )
        routes = finder.find_routes("A", "G", k=3)
        self.assertEqual(routes[0].stops, ["A", "B", "C", "D", "E", "F", "G"])
        self.assertEqual(routes[0].route_count, 1)
        self.assertEqual(routes[0].route_ids, [0])

        stops = [r.stops for r in routes]
        self.assertIn(["A", "B", "R", "G"], stops)
        alt = next(r for r in routes if r.stops == ["A", "B", "R", "G"])
        self.assertEqual(alt.route_count, 2)
        self.assertEqual(alt.route_ids, [0, 1])

    def test_transfer_counted_at_transparent_node(self):
        # B is a degree-2 (transparent) node where two authored routes meet, so
        # X->Y still merges two routes.
        finder = RouteFinder(Graph.from_routes([["X", "A", "B"], ["B", "C", "Y"]]))
        routes = finder.find_routes("X", "Y")
        self.assertEqual(routes[0].stops, ["X", "A", "B", "C", "Y"])
        self.assertEqual(routes[0].route_count, 2)
        self.assertEqual(routes[0].route_ids, [0, 1])

    def test_spec_km_reports_merged_routes(self):
        best = self.finder.find_routes("K", "M", k=3)[0]
        self.assertEqual(best.stops, ["K", "J", "E", "G", "N", "M"])
        self.assertEqual(best.route_count, 2)  # merges routes 1 and 2
        self.assertEqual(best.route_ids, [1, 2])

    def test_equal_merge_tiebreak_by_crossroad_hops(self):
        # A->R: both corridors merge 2 routes; the one crossing fewer
        # intersections (only E) wins.
        best = self.finder.find_routes("A", "R", k=3)[0]
        self.assertEqual(best.stops, ["A", "L", "K", "J", "E", "R"])
        self.assertEqual(best.route_count, 2)

    def test_via_still_works_with_merges(self):
        routes = self.finder.find_routes("K", "M", via=["E"])
        self.assertTrue(routes)
        self.assertIn("E", routes[0].stops)
        self.assertTrue(all(len(r.stops) == len(set(r.stops)) for r in routes))

    def test_k_shortest_paths_returns_stop_lists(self):
        finder = RouteFinder(
            Graph.from_routes([["A", "B", "C", "D", "E", "F", "G"], ["B", "R", "G"]])
        )
        paths = finder.k_shortest_paths("A", "G")
        self.assertEqual(paths[0], ["A", "B", "C", "D", "E", "F", "G"])
        self.assertTrue(all(isinstance(p, list) for p in paths))


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
