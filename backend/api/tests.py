"""Algorithm correctness tests, anchored on the spec's own example."""

import tempfile

from django.test import SimpleTestCase

from .db import Database, ValidationError
from .graph import Graph, LengthMode, RouteFinder, evaluate
from .views import _split_by_compromise

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
        # Best-first now means highest concentration first (non-increasing HHI).
        routes = self.finder.find_routes("A", "R", k=3)
        hhis = [r.hhi for r in routes]
        self.assertEqual(hhis, sorted(hhis, reverse=True))

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

    def test_k_none_lifts_the_cap(self):
        # Four fully disjoint S-T corridors (one per authored route): k=3 caps
        # at 3, k=None returns all of them since none overlaps/detours.
        parallel_routes = [
            ["S", "a1", "a2", "T"],
            ["S", "b1", "b2", "T"],
            ["S", "c1", "c2", "T"],
            ["S", "d1", "d2", "T"],
        ]
        finder = RouteFinder(Graph.from_routes(parallel_routes))
        capped = finder.find_routes("S", "T", k=3)
        uncapped = finder.find_routes("S", "T", k=None)
        self.assertEqual(len(capped), 3)
        self.assertEqual(len(uncapped), 4)


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

    def test_more_concentrated_corridor_wins(self):
        # A->R: both corridors merge 2 routes, but concentration decides. Riding
        # route 1 for the bulk (A-B-C then C..R) is more concentrated than the
        # balanced 50/50 [A, L, K, J, E, R], so it is the best route.
        routes = self.finder.find_routes("A", "R", k=3)
        best = routes[0]
        self.assertEqual(best.stops, ["A", "B", "C", "M", "N", "G", "E", "R"])
        self.assertEqual(best.route_count, 2)
        self.assertIn(["A", "L", "K", "J", "E", "R"], [r.stops for r in routes])
        self.assertGreater(best.hhi, routes[1].hhi)

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


# A graph with two S->T corridors: a long artery (route 0) reached by brief hops
# (routes 1, 2) — three merged routes but perfectly concentrated — and a balanced
# two-route blend (routes 6, 7). Stubs make the interior nodes crossroads.
CONCENTRATION_ROUTES = [
    ["x", "a1", "a2", "a3", "y"],   # 0: the artery
    ["S", "x"],                      # 1: entry hop onto the artery
    ["y", "T"],                      # 2: exit hop off the artery
    ["a1", "p1"],                    # 3: stub -> a1 becomes a crossroad
    ["a2", "p2"],                    # 4: stub -> a2 crossroad
    ["a3", "p3"],                    # 5: stub -> a3 crossroad
    ["S", "b1", "m"],                # 6: balanced corridor, first half
    ["m", "b2", "T"],                # 7: balanced corridor, second half
    ["b1", "q1"],                    # 8: stub -> b1 crossroad
    ["b2", "q2"],                    # 9: stub -> b2 crossroad
]

CORRIDOR_A = ["S", "x", "a1", "a2", "a3", "y", "T"]  # merges 3, HHI 1.0
CORRIDOR_B = ["S", "b1", "m", "b2", "T"]             # merges 2, HHI 0.5


class ConcentrationTests(SimpleTestCase):
    """"Best" = riding one authored route as far as possible (max concentration)."""

    def setUp(self):
        self.graph = Graph.from_routes(CONCENTRATION_ROUTES)
        self.finder = RouteFinder(self.graph)

    def test_evaluate_single_route_is_perfect(self):
        hhi, runs = evaluate(self.graph, ["x", "a1", "a2", "a3", "y"])
        self.assertAlmostEqual(hhi, 1.0)
        self.assertEqual([r.route_id for r in runs], [0])

    def test_evaluate_balanced_blend(self):
        hhi, runs = evaluate(self.graph, CORRIDOR_B)
        self.assertAlmostEqual(hhi, 0.5)  # (1/2)^2 + (1/2)^2
        # Runs are in travel order (route 6 then 7), each with equal length.
        self.assertEqual([r.route_id for r in runs], [6, 7])
        self.assertEqual([r.length for r in runs], [2, 2])

    def test_runs_are_travel_ordered_with_boundary_nodes(self):
        _, runs = evaluate(self.graph, CORRIDOR_B)
        self.assertEqual([(r.start, r.end) for r in runs], [("S", "m"), ("m", "T")])
        self.assertEqual([r.hops for r in runs], [2, 2])  # shares over 4 hops -> 50/50

    def test_evaluate_no_crossroads_falls_back(self):
        # A chain crossing no crossroads has L == 0; score falls back to 1/n.
        g = Graph.from_routes([["X", "A", "B"], ["B", "C", "Y"]])
        hhi, runs = evaluate(g, ["X", "A", "B", "C", "Y"])
        self.assertAlmostEqual(hhi, 0.5)
        self.assertEqual(sorted({r.route_id for r in runs}), [0, 1])

    def test_best_maximises_concentration_even_with_more_merges(self):
        # Non-monotonic: the 3-route artery corridor (HHI 1.0) beats the balanced
        # 2-route blend (HHI 0.5) — best may merge MORE routes to stay concentrated.
        routes = self.finder.find_routes("S", "T", k=3)
        self.assertEqual(routes[0].stops, CORRIDOR_A)
        self.assertAlmostEqual(routes[0].hhi, 1.0)
        self.assertEqual(routes[0].route_count, 3)

        self.assertEqual(len(routes), 2)
        self.assertEqual(routes[1].stops, CORRIDOR_B)
        self.assertEqual(routes[1].route_count, 2)
        self.assertGreater(routes[0].route_count, routes[1].route_count)
        self.assertGreater(routes[0].hhi, routes[1].hhi)

    def test_alternatives_are_distinct_corridors(self):
        # Real alternatives ride different arteries, not one-hop variants.
        routes = self.finder.find_routes("S", "T", k=3)
        self.assertGreaterEqual(len(routes), 2)
        self.assertTrue(
            set(routes[0].route_ids).isdisjoint(routes[1].route_ids),
            "alternatives share a dominant route",
        )

    def test_length_mode_flag_changes_score(self):
        # Crossroads-only, the brief end-hops are length-0 so the artery is a
        # perfect ride; counting every hop, they weigh in and the score drops.
        self.assertAlmostEqual(evaluate(self.graph, CORRIDOR_A)[0], 1.0)
        LengthMode.CROSSROADS_ONLY = False
        try:
            hhi = evaluate(self.graph, CORRIDOR_A)[0]
        finally:
            LengthMode.CROSSROADS_ONLY = True
        self.assertAlmostEqual(hhi, 0.5)  # runs 1,4,1 -> (1+16+1)/36

    def test_evaluate_is_direction_independent(self):
        # The objective must be identical for a chain and its reverse.
        for chain in (CORRIDOR_A, CORRIDOR_B, ["S", "b1", "m", "b2", "T"]):
            self.assertAlmostEqual(
                evaluate(self.graph, chain)[0],
                evaluate(self.graph, chain[::-1])[0],
            )

    def test_find_routes_is_symmetric(self):
        # A route and its reverse are equally good, so the best match a query
        # yields must not depend on which endpoint is the start.
        for a, b in [("S", "T"), ("S", "b2"), ("x", "T")]:
            fwd = self.finder.find_routes(a, b, k=3)
            rev = self.finder.find_routes(b, a, k=3)
            self.assertAlmostEqual(fwd[0].hhi, rev[0].hhi)
            # same corridor, just walked the other way
            self.assertEqual(fwd[0].stops, rev[0].stops[::-1])


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

    def test_without_places_drops_node_and_incident_edges(self):
        graph = Graph.from_routes([["A", "B", "C"], ["B", "D"]])
        trimmed = graph.without_places(["B"])
        self.assertNotIn("B", trimmed)
        self.assertIn("A", trimmed)
        self.assertIn("C", trimmed)
        self.assertIn("D", trimmed)
        self.assertEqual(trimmed.neighbors("A"), [])
        self.assertEqual(trimmed.neighbors("C"), [])
        self.assertEqual(trimmed.neighbors("D"), [])

    def test_without_places_leaves_other_edges_intact(self):
        graph = Graph.from_routes([["A", "B", "C"]])
        trimmed = graph.without_places(["Z"])  # nothing to remove
        self.assertEqual(trimmed.neighbors("A"), ["B"])
        self.assertEqual(trimmed.neighbors("B"), ["A", "C"])


class CompromisedDestinationsTests(SimpleTestCase):
    """Compromised destinations are excluded from routing/place-picking but
    never removed from routes.json/edge_routes.json themselves."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Database(data_dir=self.tmp.name)
        self.db.save_routes([["A", "B", "C"], ["C", "D", "E"]])

    def test_defaults_to_empty(self):
        self.assertEqual(self.db.load_compromised(), [])
        self.assertEqual(self.db.compromised_places(), set())

    def test_save_and_load_roundtrip(self):
        saved = self.db.save_compromised([["B"], ["D", "E"]])
        self.assertEqual(saved, [["B"], ["D", "E"]])
        self.assertEqual(self.db.load_compromised(), [["B"], ["D", "E"]])
        self.assertEqual(self.db.compromised_places(), {"B", "D", "E"})

    def test_rejects_unknown_destination(self):
        with self.assertRaises(ValidationError):
            self.db.save_compromised([["ZZZ"]])

    def test_rejects_empty_group(self):
        with self.assertRaises(ValidationError):
            self.db.save_compromised([[]])

    def test_routable_graph_excludes_compromised_places(self):
        self.db.save_compromised([["C"]])
        graph = self.db.load_routable_graph()
        self.assertNotIn("C", graph)
        self.assertIn("A", graph)
        self.assertIn("D", graph)

    def test_full_graph_still_includes_compromised_places(self):
        self.db.save_compromised([["C"]])
        graph = self.db.load_graph()
        self.assertIn("C", graph)

    def test_routing_avoids_compromised_destination(self):
        self.db.save_compromised([["C"]])
        graph = self.db.load_routable_graph()
        finder = RouteFinder(graph)
        # C was the only link between the two routes' halves, so it's now
        # unreachable and A-E has no route.
        self.assertEqual(finder.k_shortest_paths("A", "E"), [])


class DetourNoticeTests(SimpleTestCase):
    """`_split_by_compromise` (backend/api/views.py) — computed from a single
    RouteFinder run against the FULL graph: which compromised destinations the
    natural, unfiltered top-3 would have used, and which of the ranked results
    are actually clean (usable as the real response)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Database(data_dir=self.tmp.name)
        self.db.save_routes([["A", "B", "C"], ["C", "D", "E"]])

    def test_sole_connector_compromised_shows_up_in_detour(self):
        self.db.save_compromised([["C"]])
        results = RouteFinder(self.db.load_graph()).find_routes("A", "E", k=None)
        clean, detour = _split_by_compromise(results, self.db.compromised_places())
        self.assertEqual(detour, ["C"])
        self.assertEqual(clean, [])

    def test_nothing_compromised_leaves_results_untouched(self):
        results = RouteFinder(self.db.load_graph()).find_routes("A", "E", k=None)
        clean, detour = _split_by_compromise(results, self.db.compromised_places())
        self.assertEqual(detour, [])
        self.assertEqual(clean, results)

    def test_unrelated_compromise_does_not_trigger_detour(self):
        # F is an unrelated branch off C; the natural A-E route never touches it.
        self.db.save_routes([["A", "B", "C"], ["C", "D", "E"], ["C", "F"]])
        self.db.save_compromised([["F"]])
        results = RouteFinder(self.db.load_graph()).find_routes("A", "E", k=None)
        clean, detour = _split_by_compromise(results, self.db.compromised_places())
        self.assertEqual(detour, [])
        self.assertEqual(clean, results)
