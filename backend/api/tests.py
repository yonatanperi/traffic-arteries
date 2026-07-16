"""Algorithm correctness tests, anchored on the spec's own example."""

import os
from unittest import mock

import boto3
from django.test import SimpleTestCase
from moto import mock_aws

from .db import Database, ValidationError
from .graph import Graph, LengthMode, PriorityMode, RouteFinder, evaluate, tier
from .graph.search import MinMergeStrategy, avoid_priority_penalty

# The example from the spec.
SPEC_ROUTES = [
    ["A", "B", "C", "D"],
    ["C", "M", "N", "G", "E", "R"],
    ["E", "J", "K", "L", "A"],
]

# Dummy R2 credentials + an AWS-style endpoint override so moto's mock (which only
# recognizes AWS hostnames, not R2's) intercepts the boto3 calls in-process.
_R2_TEST_ENV = {
    "R2_ACCOUNT_ID": "test",
    "R2_ACCESS_KEY_ID": "test",
    "R2_SECRET_ACCESS_KEY": "test",
    "R2_BUCKET_NAME": "traffic-arteries-test",
    "R2_ENDPOINT_URL": "https://s3.amazonaws.com",
}


class R2BackedTestCase(SimpleTestCase):
    """Backs the R2-persisted :class:`Database` with an in-process S3 mock, so the
    storage tests run offline against a fresh bucket per test."""

    def setUp(self):
        super().setUp()
        env = mock.patch.dict(os.environ, _R2_TEST_ENV)
        env.start()
        self.addCleanup(env.stop)

        self._aws_mock = mock_aws()
        self._aws_mock.start()
        self.addCleanup(self._aws_mock.stop)

        boto3.client(
            "s3",
            aws_access_key_id="test",
            aws_secret_access_key="test",
            region_name="us-east-1",
        ).create_bucket(Bucket=_R2_TEST_ENV["R2_BUCKET_NAME"])

        self.db = Database()


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


# Two S->T corridors that put the tier and the score in direct conflict:
#   * the "patchwork" [S, c1, c2, c3, T] stitches four *well-rated* routes — poorly
#     concentrated (it transfers at every stop) but never leaves priority 0.
#   * the "clean ride" [S, q1, q2, T] is a single artery end to end — perfectly
#     concentrated, and shorter — but that artery is rated below best.
# Stubs (routes 5..9) make the interior nodes crossroads so they carry length.
PRIORITY_ROUTES = [
    ["S", "c1"],              # 0: patchwork, leg 1
    ["c1", "c2"],             # 1: patchwork, leg 2
    ["c2", "c3"],             # 2: patchwork, leg 3
    ["c3", "T"],              # 3: patchwork, leg 4
    ["S", "q1", "q2", "T"],   # 4: the clean single artery
    ["c1", "z1"],             # 5..9: stubs -> the interior nodes are crossroads
    ["c2", "z2"],
    ["c3", "z3"],
    ["q1", "z4"],
    ["q2", "z5"],
]
# Only the clean artery is downgraded; every other route stays best-priority.
DOWNGRADED_ARTERY = [0, 0, 0, 0, 1, 0, 0, 0, 0, 0]

PATCHWORK = ["S", "c1", "c2", "c3", "T"]   # tier 0, score 0.28 — badly concentrated
CLEAN_RIDE = ["S", "q1", "q2", "T"]        # tier 1, score 0.80 — but poorly rated


class PriorityTests(SimpleTestCase):
    """Priority is a hard tier over the concentration score: the worst authored-route
    priority a route is forced to touch outranks how well it rides anything."""

    def setUp(self):
        self.graph = Graph.from_routes(PRIORITY_ROUTES, DOWNGRADED_ARTERY)
        self.finder = RouteFinder(self.graph)

    def test_weight_discounts_a_downgraded_artery(self):
        # Riding one priority-1 artery end to end: a perfect ride, scored w(1) = 0.8.
        score, runs = evaluate(self.graph, CLEAN_RIDE)
        self.assertAlmostEqual(score, 0.8)
        self.assertEqual([r.route_id for r in runs], [4])
        self.assertEqual([r.priority for r in runs], [1])

    def test_best_priority_artery_still_scores_a_perfect_one(self):
        # The weighting must not move the ceiling: an unrated artery still hits 1.0.
        graph = Graph.from_routes(PRIORITY_ROUTES)  # nothing downgraded
        self.assertAlmostEqual(evaluate(graph, CLEAN_RIDE)[0], 1.0)

    def test_tier_is_the_worst_priority_the_chain_must_touch(self):
        self.assertEqual(tier(self.graph, PATCHWORK), 0)
        self.assertEqual(tier(self.graph, CLEAN_RIDE), 1)

    def test_hard_tier_beats_a_better_concentrated_route(self):
        # The whole point of HARD_TIER: the patchwork rides four arteries and scores
        # 0.28, the clean ride is a single artery at 0.80 — and the patchwork still
        # wins, because it never leaves priority 0.
        routes = self.finder.find_routes("S", "T", k=3)
        self.assertEqual(routes[0].stops, PATCHWORK)
        self.assertEqual(routes[0].priority, 0)
        self.assertLess(routes[0].hhi, routes[1].hhi)  # it won *despite* scoring worse

    def test_alternatives_fall_through_to_worse_tiers(self):
        # Priority ranks, it never filters. The best tier holds only one corridor
        # here, so the alternative must come from a worse tier rather than the
        # result list collapsing to a single route.
        routes = self.finder.find_routes("S", "T", k=3)
        self.assertEqual(len(routes), 2)
        self.assertEqual(routes[1].stops, CLEAN_RIDE)
        self.assertEqual(routes[1].priority, 1)
        self.assertAlmostEqual(routes[1].hhi, 0.8)

    def test_soft_mode_lets_the_better_route_win(self):
        # Drop the tier from the ranking and the weighted score alone decides, so
        # the clean (if poorly-rated) ride takes the lead.
        PriorityMode.HARD_TIER = False
        try:
            routes = self.finder.find_routes("S", "T", k=3)
        finally:
            PriorityMode.HARD_TIER = True
        self.assertEqual(routes[0].stops, CLEAN_RIDE)
        self.assertAlmostEqual(routes[0].hhi, 0.8)

    def test_avoid_priority_penalty_finds_the_tier_clean_corridor(self):
        # The generator pass that puts the patchwork in the pool at all: confined to
        # priority-0 arteries, the only way from S to T is the long way round.
        strategy = MinMergeStrategy(self.graph, "S", "T")
        nodes, _ = strategy.find(avoid_priority_penalty(self.graph, 0))
        self.assertEqual(nodes, PATCHWORK)
        # Unconstrained, the same search takes the clean (downgraded) artery — which
        # is exactly why the tier-clean corridor needs a pass of its own.
        self.assertEqual(strategy.find({})[0], CLEAN_RIDE)


class PriorityTierFollowsRiddenRouteTests(SimpleTestCase):
    """The tier is the worst priority among the sub-routes actually ridden (the
    max-HHI credit assignment / the UI's chips) — NOT an edge-only best. When
    riding one authored route as far as possible means riding a downgraded one,
    the route inherits that downgrade, even where the same road is co-served by a
    well-rated route."""

    # Every edge of S..T is carried by BOTH the downgraded through-route (0) and a
    # well-rated single-hop route. So per-edge the road is priority-0 drivable — but
    # only route 0 spans it in a single concentrated run.
    ROUTES = [
        ["S", "u1", "u2", "u3", "T"],  # 0: the downgraded through-artery
        ["S", "u1"],                   # 1..4: well-rated legs covering the same edges
        ["u1", "u2"],
        ["u2", "u3"],
        ["u3", "T"],
        ["u1", "z1"],                  # 5..7: stubs -> interior nodes are crossroads
        ["u2", "z2"],
        ["u3", "z3"],
    ]
    PRIORITIES = [2, 0, 0, 0, 0, 0, 0, 0]
    CHAIN = ["S", "u1", "u2", "u3", "T"]

    def setUp(self):
        self.graph = Graph.from_routes(self.ROUTES, self.PRIORITIES)

    def test_score_credits_the_long_run_to_the_downgraded_artery(self):
        # One 6-long run on the priority-2 artery scores 0.6·36/36 = 0.6; splitting
        # the same chain across the four well-rated legs scores only 10/36 ≈ 0.28.
        # So the score-maximising assignment rides the *downgraded* artery.
        score, runs = evaluate(self.graph, self.CHAIN)
        self.assertAlmostEqual(score, 0.6)
        self.assertEqual([r.route_id for r in runs], [0])
        self.assertEqual([r.priority for r in runs], [2])

    def test_tier_follows_the_ridden_sub_route(self):
        # The chain is ridden as one run on the priority-2 artery, so the route is
        # tier 2 — even though every edge is *also* on a priority-0 route. Riding it
        # as those p0 legs is less concentrated, so that isn't how it's ridden.
        self.assertEqual(tier(self.graph, self.CHAIN), 2)
        # The per-edge best is still 0 — that's what generation uses to hunt for a
        # physically different corridor, but it is not the route's tier.
        self.assertEqual(self.graph.edge_priority("u1", "u2"), 0)

    def test_ranking_prefers_a_genuinely_better_rated_corridor_when_one_exists(self):
        # Add a physically separate all-priority-0 detour S->d->T. It's less
        # concentrated (two arteries) but never rides the downgraded one, so hard
        # tiering puts it first and the concentrated priority-2 ride second.
        graph = Graph.from_routes(
            self.ROUTES + [["S", "d1", "d2"], ["d2", "d3", "T"], ["d1", "z8"], ["d2", "z9"]],
            self.PRIORITIES + [0, 0, 0, 0],
        )
        results = RouteFinder(graph).find_routes("S", "T", k=3)
        self.assertEqual(results[0].priority, 0)
        self.assertNotIn(0, results[0].route_ids)  # does not ride the downgraded artery
        self.assertEqual(results[1].priority, 2)   # the concentrated ride is still offered


# A strong tier-0 headline, a competitive tier-1 corridor, and two weaker tier-0
# corridors. Under the old priority-first sort the top-3 would be the three tier-0
# routes and the tier-1 one would never show. Under the priority arena, once #1
# (the strong tier-0) is taken the arena opens to 1 and the concentrated tier-1
# corridor out-concentrates the weak tier-0 alternatives, surfacing at #2.
ARENA_ROUTES = [
    ["S", "a1", "a2", "a3", "T"],   # 0: strong tier-0 single artery -> hhi 1.0
    ["S", "q1", "q2", "q3", "T"],   # 1: tier-1 single artery       -> hhi 0.8
    ["S", "b1", "b2"],              # 2..3: weak tier-0 patchwork    -> hhi 0.5
    ["b2", "b3", "T"],
    ["S", "c1", "c2"],              # 4..5: another weak tier-0 patchwork
    ["c2", "c3", "T"],
    # stubs so every interior node is a real crossroad (carries length)
    ["a1", "za1"], ["a2", "za2"], ["a3", "za3"],
    ["q1", "zq1"], ["q2", "zq2"], ["q3", "zq3"],
    ["b1", "zb1"], ["b2", "zb2"], ["b3", "zb3"],
    ["c1", "zc1"], ["c2", "zc2"], ["c3", "zc3"],
]
ARENA_PRIORITIES = [0, 1, 0, 0, 0, 0] + [0] * 12


class PriorityArenaTests(SimpleTestCase):
    """The priority arena surfaces a concentrated tier>0 corridor as an
    alternative once it out-concentrates the remaining same-or-lower-tier
    options — instead of the top-3 collapsing to only tier-0 routes."""

    def setUp(self):
        self.graph = Graph.from_routes(ARENA_ROUTES, ARENA_PRIORITIES)
        self.finder = RouteFinder(self.graph)

    def test_concentrated_higher_tier_surfaces_as_alternative(self):
        results = self.finder.find_routes("S", "T", k=3)
        self.assertEqual([r.priority for r in results], [0, 1, 0])
        # #1 is the perfect tier-0 ride; #2 is the tier-1 artery, which surfaces
        # even though the displaced tier-0 alternative (#3) is *less* concentrated.
        self.assertAlmostEqual(results[0].hhi, 1.0)
        self.assertAlmostEqual(results[1].hhi, 0.8)
        self.assertGreater(results[1].hhi, results[2].hhi)

    def test_headline_is_still_the_best_tier_zero_route(self):
        # The arena never demotes the genuine best: round one admits only tier 0.
        results = self.finder.find_routes("S", "T", k=3)
        self.assertEqual(results[0].stops, ["S", "a1", "a2", "a3", "T"])
        self.assertEqual(results[0].priority, 0)


class SelectDiverseExclusionTests(SimpleTestCase):
    """`select_diverse(exclude=...)` drops any candidate touching an excluded
    place from the pool up front, so it never occupies a slot nor spends the
    diversity budget — the generic hook views.path uses for compromised places."""

    # Two disjoint S->T corridors, one through M and one through N.
    ROUTES = [["S", "M", "T"], ["S", "N", "T"], ["M", "zm"], ["N", "zn"]]

    def setUp(self):
        self.finder = RouteFinder(Graph.from_routes(self.ROUTES))

    def test_excluded_place_is_kept_out_of_results(self):
        ranked, stretch = self.finder.rank_candidates("S", "T")
        # Unfiltered, both corridors are offered.
        both = self.finder.select_diverse(ranked, k=None, max_stretch=stretch)
        self.assertIn(["S", "M", "T"], [r.stops for r in both])
        self.assertIn(["S", "N", "T"], [r.stops for r in both])
        # Excluding M leaves only the N corridor — selected over the same pool,
        # no re-rank.
        clean = self.finder.select_diverse(
            ranked, k=None, max_stretch=stretch, exclude={"M"}
        )
        self.assertEqual([r.stops for r in clean], [["S", "N", "T"]])


class PriorityCostGuardTests(SimpleTestCase):
    """With nothing downgraded, priority cannot change any ranking — so none of the
    priority-aware machinery may run."""

    def test_unrated_graph_reports_no_priorities(self):
        graph = Graph.from_routes(SPEC_ROUTES)
        self.assertFalse(graph.has_priorities())
        self.assertEqual(graph.worst_priority(), 0)
        # `worst_priority() == 0` is what zeroes the per-tier generation loop, and
        # `has_priorities()` what skips the per-artery one.
        self.assertEqual(list(range(graph.worst_priority())), [])

    def test_explicit_all_best_priorities_are_still_no_priorities(self):
        # Passing all-zeroes is the same as passing nothing — the common case once
        # the editor writes an explicit priority onto every route.
        graph = Graph.from_routes(SPEC_ROUTES, [0, 0, 0])
        self.assertFalse(graph.has_priorities())

    def test_unrated_graph_scores_exactly_as_before(self):
        graph = Graph.from_routes(SPEC_ROUTES)
        routes = RouteFinder(graph).find_routes("K", "M", k=3)
        self.assertEqual(routes[0].stops, ["K", "J", "E", "G", "N", "M"])
        self.assertEqual(routes[0].priority, 0)


class RoutePriorityStorageTests(R2BackedTestCase):
    """routes.json stores {places, priority}; the bare-list shape predating
    priorities still loads, as all-best-priority."""

    def test_saves_and_loads_priority(self):
        saved = self.db.save_routes(
            [{"places": ["A", "B", "C"], "priority": 2}, {"places": ["C", "D"], "priority": 0}]
        )
        self.assertEqual(saved[0], {"places": ["A", "B", "C"], "priority": 2})
        self.assertEqual(self.db.load_routes(), saved)
        self.assertEqual(self.db.load_graph().route_priority(0), 2)

    def test_legacy_bare_lists_load_as_best_priority(self):
        # Written before priorities existed; must still load, and be upgraded on save.
        self.db.save_routes([["A", "B", "C"]])
        self.assertEqual(self.db.load_routes(), [{"places": ["A", "B", "C"], "priority": 0}])
        self.assertFalse(self.db.load_graph().has_priorities())

    def test_priority_survives_the_derived_graph_rebuild(self):
        # Priorities live only in routes.json — edge_routes.json never carries them,
        # so this proves they're re-attached on load rather than lost.
        self.db.save_routes([{"places": ["A", "B", "C"], "priority": 3}])
        graph = self.db.load_graph()
        self.assertEqual(graph.edge_priority("A", "B"), 3)
        self.assertEqual(graph.worst_priority(), 3)

    def test_routable_graph_keeps_priorities(self):
        self.db.save_routes(
            [{"places": ["A", "B", "C"], "priority": 2}, {"places": ["C", "D"], "priority": 0}]
        )
        self.db.save_compromised([["D"]])
        self.assertEqual(self.db.load_routable_graph().route_priority(0), 2)

    def test_rejects_out_of_range_priority(self):
        with self.assertRaises(ValidationError):
            self.db.save_routes([{"places": ["A", "B"], "priority": 4}])
        with self.assertRaises(ValidationError):
            self.db.save_routes([{"places": ["A", "B"], "priority": -1}])

    def test_rejects_non_integer_priority(self):
        for bad in ("1", 1.5, None, True):
            with self.assertRaises(ValidationError):
                self.db.save_routes([{"places": ["A", "B"], "priority": bad}])


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


class CompromisedDestinationsTests(R2BackedTestCase):
    """Compromised destinations are excluded from routing/place-picking but
    never removed from routes.json/edge_routes.json themselves."""

    def setUp(self):
        super().setUp()
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


class DetourNoticeTests(R2BackedTestCase):
    """The compromised split in views.path: one ranked pool (a single sort),
    selected twice — the natural best (to report which compromised destinations
    the top-N would have used) and the best avoiding them (the real response)."""

    TOP_N = 3

    def setUp(self):
        super().setUp()
        self.db.save_routes([["A", "B", "C"], ["C", "D", "E"]])

    def _split(self, start, end):
        """Mirror views.path: rank once, select natural + compromised-free."""
        finder = RouteFinder(self.db.load_graph())
        compromised = self.db.compromised_places()
        ranked, stretch = finder.rank_candidates(start, end)
        natural = finder.select_diverse(ranked, k=None, max_stretch=stretch)
        detour = (
            sorted({s for r in natural[: self.TOP_N] for s in r.stops} & compromised)
            if compromised
            else []
        )
        clean = (
            finder.select_diverse(ranked, k=None, max_stretch=stretch, exclude=compromised)
            if compromised
            else natural
        )
        return [r.stops for r in clean], detour, [r.stops for r in natural]

    def test_sole_connector_compromised_shows_up_in_detour(self):
        self.db.save_compromised([["C"]])
        clean, detour, _ = self._split("A", "E")
        self.assertEqual(detour, ["C"])
        self.assertEqual(clean, [])

    def test_nothing_compromised_leaves_results_untouched(self):
        clean, detour, natural = self._split("A", "E")
        self.assertEqual(detour, [])
        self.assertEqual(clean, natural)  # clean is exactly the natural selection

    def test_unrelated_compromise_does_not_trigger_detour(self):
        # F is an unrelated branch off C; the natural A-E route never touches it.
        self.db.save_routes([["A", "B", "C"], ["C", "D", "E"], ["C", "F"]])
        self.db.save_compromised([["F"]])
        clean, detour, natural = self._split("A", "E")
        self.assertEqual(detour, [])
        self.assertEqual(clean, natural)  # excluding an unused place changes nothing
