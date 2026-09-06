"""Algorithm correctness tests, anchored on the spec's own example."""

import contextlib
import os
import tempfile
from unittest import mock

import boto3
from django.test import SimpleTestCase, override_settings
from moto import mock_aws

from . import db as db_module
from .db import Database, ValidationError, expand_route, expand_routes, upgrade_node
from .graph import Graph, LengthMode, PriorityMode, RouteFinder, evaluate, tier
from .graph.concentration import edge_unit
from .graph.search import MinMergeStrategy, avoid_priority_penalty, prefer_route_penalty
from .management.commands.migrate_place_groups import Command as MigratePlaceGroupsCommand
from .place_groups import DEFAULT_GROUP
from utils.r2_storage import storage

@contextlib.contextmanager
def length_mode(crossroads_only):
    """Run a block under a given :class:`LengthMode`, restoring the previous one.

    The mode is a process-wide static flag, so a test that flips it must put back
    what it found — not a hardcoded value, or it silently redefines the default
    for every test after it.
    """
    previous = LengthMode.CROSSROADS_ONLY
    LengthMode.CROSSROADS_ONLY = crossroads_only
    try:
        yield
    finally:
        LengthMode.CROSSROADS_ONLY = previous


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

    def id(self, name):
        """The internal place id for a display-name string already saved via
        ``self.db.save_routes``/``save_compromised`` — places are now stored by
        id, not name, so most graph/routing assertions need this to translate a
        human-readable test name into what the graph actually holds."""
        return self.db.place_id(name)

    def ids(self, names):
        return [self.id(n) for n in names]

    def names(self, place_ids):
        return self.db.translate_stops(place_ids)

    def register(self, name, group="other"):
        """Mint/reuse an id for ``name`` directly in the place registry, without
        touching routes.json — for tests that write routes.json out of band
        (bypassing ``save_routes``'s own id resolution) and need a real,
        persisted id for a stop that isn't part of any saved route yet."""
        registry = self.db.load_place_registry()
        by_group_base = self.db._by_group_base(registry)
        next_id_ref = [self.db._next_id(registry)]
        place_id = self.db._resolve_or_create(name, registry, by_group_base, next_id_ref)
        self.db._atomic_write_json(self.db.places_key, {str(k): v for k, v in registry.items()})
        return place_id


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
        # Pinned to hop-count length: this fixture crosses almost no crossroads, so
        # crossroads-only collapses its lengths to 0 and evaluate() falls back to the
        # equal-share 1/n — which says nothing about the ordering under test.
        with length_mode(False):
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
    """Required intermediate stops: real-world routes, no pointless detour."""

    # A-B direct; A-C and C-B direct (short way through C); a long *single-route*
    # road from A to C via Z, X, N, K; a long *fragmented* one (routes 4..8,
    # transferring at every other stop) that exists only to be rejected for
    # length; and a dead-end spur C-P, reachable only by turning around.
    WAYPOINT_ROUTES = [
        ["A", "B"],                          # 0
        ["A", "C"],                          # 1
        ["C", "B"],                          # 2
        ["A", "Z", "X", "N", "K", "C"],      # 3: long, but one road end to end
        ["A", "w1", "w2"],                   # 4..8: long AND fragmented
        ["w2", "w3", "w4"],
        ["w4", "w5", "w6"],
        ["w6", "w7", "w8"],
        ["w8", "w9", "C"],
        ["C", "P"],                          # 9: dead end (P has degree 1)
    ]
    LONG_FRAGMENTED = ["A", "w1", "w2", "w3", "w4", "w5", "w6", "w7", "w8", "w9", "C", "B"]

    # A *through* stop: V hangs off the highway at J but has its own good road
    # onward to T, so driving straight through it is the better ride and nothing
    # should double back. The stubs matter: without them c1/c2 are transparent and
    # V's whole road onward measures *zero* length, which under
    # LengthMode.CROSSROADS_ONLY makes any detour along it free and the fixture stops
    # saying anything about routing at all.
    THROUGH_STOP_ROUTES = [
        ["S", "h1", "J", "h2", "T"],  # 0: one highway, end to end
        ["J", "V"],                   # 1: the turn-off onto V
        ["V", "c1", "c2", "T"],       # 2: V's own road onward, one artery
        ["c1", "zc1"], ["c2", "zc2"], # 3..4: stubs — c1/c2 are real junctions
    ]

    # Two required stops where one leg is *tempted* to collect the other's stop:
    # the direct road to W1 is fragmented, while the road that runs through W2 gets
    # there on a single artery and so scores better. Letting it do that leaves the
    # W2 leg doubling back over ground the W1 leg already drove.
    TWO_STOP_ROUTES = [
        ["S", "a1"], ["a1", "W1"],           # 0..1: the direct way to W1, fragmented
        ["S", "b1", "W2", "b2", "W1"],       # 2: one artery to W1 — through W2
        ["W2", "c1", "T"],                   # 3
        ["W1", "d1", "T"],                   # 4
        ["a1", "za"], ["b1", "zb"], ["b2", "zb2"],  # stubs, as above
        ["c1", "zc"], ["d1", "zd"],
    ]

    # The trip's own start sitting *on the road* the second leg needs: S is a
    # transparent degree-2 point partway along the artery, and the required stop K is
    # at the end of the spur past it. The drive is out to K and back down through S.
    # A guard that keeps a leg off the trip's endpoints — worse, one that deletes
    # them from the graph, which severs the road a degree-2 point carries rather than
    # routing around it — pushes the second leg onto the fragmented bypass instead.
    START_ON_THE_WAY_ROUTES = [
        ["K", "n1", "S", "m1", "T"],                   # 0: the artery, through S
        ["K", "p1"], ["p1", "p2"], ["p2", "T"],        # 1..3: fragmented bypass
        ["n1", "zn"], ["m1", "zm"],                    # stubs, as above
        ["p1", "zp1"], ["p2", "zp2"],
    ]

    # The mirror image, and the shape of the reported bug: W is a *spur* off the
    # junction J. It does have a way onward to T (x1-x2), but that way is fragmented
    # and crosses two more junctions, so backing out through J and carrying on down
    # the one highway is both shorter and far better concentrated. A search that bans
    # retracing outright can never propose it — which is exactly what
    # `מ. מש"א חיפה -> מ. צוקי עובדה בהל"צ via צ. הנשיא` used to hit on the live
    # network, where צ. הנשיא hangs off מחלף בית קמה the same way.
    SPUR_STOP_ROUTES = [
        ["S", "h1", "J", "h2", "T"],  # 0: one highway, end to end
        ["J", "W"],                   # 1: the turn-off onto the W spur
        ["W", "x1"],                  # 2..4: W's own way onward, transferring
        ["x1", "x2"],                 #       at every stop
        ["x2", "T"],
        ["x1", "s1"],                 # 5..6: stubs, so x1/x2 are real junctions and
        ["x2", "s2"],                 #       that way onward genuinely costs crossroads
    ]

    def setUp(self):
        self.finder = RouteFinder(Graph.from_routes(self.WAYPOINT_ROUTES))

    @staticmethod
    def _legs(path, stops):
        """Split a stop chain into its legs — the stretches between required stops."""
        legs, current = [], [path[0]]
        for node in path[1:]:
            current.append(node)
            if node in stops:
                legs.append(current)
                current = [node]
        legs.append(current)
        return [leg for leg in legs if len(leg) > 1]

    def test_route_passes_through_required_stop(self):
        for p in self.finder.k_shortest_paths("A", "B", via=["C"]):
            self.assertIn("C", p)

    def test_no_loops_within_a_leg(self):
        # Simplicity is scoped to the leg, not the whole route: retracing across a
        # required stop is legitimate (it is how a spur is left), looping inside
        # one leg never is.
        for p in self.finder.k_shortest_paths("A", "B", via=["P"]):
            for leg in self._legs(p, {"P"}):
                self.assertEqual(len(leg), len(set(leg)), f"leg loops on itself: {leg}")

    def test_no_avoidable_retracing(self):
        # Retracing is a cost, not a ban. V has its own good road onward, so driving
        # straight through is the better ride and must win; the route that backs out
        # onto the highway is still *offered* — searching a leg at a time is what
        # lets the spur case below be found at all — but never leads.
        finder = RouteFinder(Graph.from_routes(self.THROUGH_STOP_ROUTES))
        routes = finder.find_routes("S", "T", via=["V"])
        self.assertTrue(routes, "no route through the required stop")
        best = routes[0].stops
        self.assertEqual(best, ["S", "h1", "J", "V", "c1", "c2", "T"])
        self.assertEqual(len(best), len(set(best)), f"headline doubles back: {best}")
        for route in routes[1:]:
            if len(route.stops) != len(set(route.stops)):
                self.assertLess(
                    route.q, routes[0].q, f"retracing route ranks first: {route.stops}"
                )

    def test_spur_stop_is_left_by_backing_out(self):
        # The reported bug. W hangs off the junction J; its own way onward exists but
        # is fragmented, so the good corridor arrives at W and drives back out through
        # J. Minimising revisits ahead of everything else — what the old whole-sequence
        # waypoint search did — makes that corridor unreachable, not merely unpopular:
        # it is never generated, so no amount of scoring can recover it. Searching each
        # leg on its own is what puts it in the pool.
        finder = RouteFinder(Graph.from_routes(self.SPUR_STOP_ROUTES))
        routes = finder.find_routes("S", "T", via=["W"])
        self.assertTrue(routes, "no route through the spur stop")
        self.assertEqual(routes[0].stops, ["S", "h1", "J", "W", "J", "h2", "T"])

    def test_a_leg_does_not_collect_another_legs_stop(self):
        # A leg may not drive through a required stop that is not its own: that
        # collects a stop belonging to another leg, and leaves that leg doubling back
        # over ground already driven. Here the temptation is real — the road to W1
        # through W2 is a single artery where the direct one is fragmented, so without
        # the guard it leads the W1 leg outright.
        finder = RouteFinder(Graph.from_routes(self.TWO_STOP_ROUTES))
        stops = {"W1", "W2"}
        routes = finder.find_routes("S", "T", via=["W1", "W2"])
        self.assertTrue(routes, "no route through the required stops")
        for route in routes:
            for leg in route.legs:
                interior = route.stops[leg.start_index + 1 : leg.end_index]
                self.assertFalse(
                    stops.intersection(interior),
                    f"leg collects another leg's stop: {route.stops}",
                )

    def test_the_stop_guard_yields_when_there_is_no_other_way(self):
        # It is a *soft* ban, so it costs a detour rather than cutting the network:
        # P hangs off C by a single edge, so a trip through both can only reach P
        # through C. Deleting C would leave the leg unroutable.
        finder = RouteFinder(Graph.from_routes(self.WAYPOINT_ROUTES))
        routes = finder.find_routes("A", "B", via=["C", "P"])
        self.assertTrue(routes, "no route when one stop is only reachable via another")
        for route in routes:
            self.assertIn("P", route.stops)
            self.assertIn("C", route.stops)

    def test_a_leg_may_drive_back_through_the_trip_start(self):
        # The mirror of the case above, and the reason the guard covers the required
        # stops only. S is a transparent point on the artery that leads to K, so
        # collecting K means driving out and back down through S — the ordinary shape
        # of a stop that lies off to one side. Keeping a leg off the trip's own
        # endpoints (or deleting them, which severs the road a degree-2 point carries)
        # forces the fragmented bypass instead, at a far worse score.
        finder = RouteFinder(Graph.from_routes(self.START_ON_THE_WAY_ROUTES))
        routes = finder.find_routes("S", "T", via=["K"])
        self.assertTrue(routes, "no route out to the spur stop and back")
        self.assertEqual(routes[0].stops, ["S", "n1", "K", "n1", "S", "m1", "T"])
        self.assertAlmostEqual(routes[0].hhi, 1.0)

    def test_retracing_is_no_more_than_forced(self):
        # When retracing *is* forced, it is minimal: leaving the P spur costs one
        # revisit — C, the node P hangs off — and every other node is driven once.
        for p in self.finder.k_shortest_paths("A", "B", via=["P"]):
            repeated = sorted(node for node in set(p) if p.count(node) > 1)
            self.assertEqual(repeated, ["C"], f"route retraces more than forced: {p}")

    def test_dead_end_stop_is_reachable(self):
        # P hangs off C by a single edge, so the only way out of P is back through
        # C. Requiring a globally simple path makes P — and every other degree-1
        # place — unroutable as a required stop; the leg-wise rule finds it.
        paths = self.finder.k_shortest_paths("A", "B", via=["P"])
        self.assertTrue(paths, "no route through a dead-end required stop")
        for p in paths:
            self.assertIn("P", p)
            i = p.index("P")
            self.assertEqual((p[i - 1], p[i + 1]), ("C", "C"))

    def test_a_required_stop_stops_one_road_dominating_the_other_leg(self):
        # Both ways from A to C ride a *single* authored road end to end: the direct
        # A-C (road 1) and the long A-Z-X-N-K-C (road 3, with Z-X-N-K transparent).
        # Requiring C therefore makes them exactly equal on the objective — leg 1
        # scores 1.0 either way, leg 2 (C-B) is the same road for both — and, since
        # Z-X-N-K cross no junction, they even cost the same crossroad distance. So
        # nothing about concentration separates them and the raw hop count breaks the
        # tie, shortest first.
        #
        # Undivided, the long way used to win: road 3's five-hop stint dominated the
        # single-hop C-B tail, so the whole-route Herfindahl preferred it. Pooling
        # credit across a required stop like that is exactly what leg-wise scoring
        # drops — the driver stops at C, so what road got them there cannot be traded
        # against what road takes them onward. Note the long corridor is then out of
        # range anyway: at 7 stops against the best route's 3 it exceeds
        # WAYPOINT_MAX_STRETCH, the same rule that rejects LONG_FRAGMENTED below.
        routes = self.finder.find_routes("A", "B", via=["C"])
        self.assertEqual(routes[0].stops, ["A", "C", "B"])
        self.assertAlmostEqual(routes[0].hhi, 1.0)
        self.assertEqual([leg.hhi for leg in routes[0].legs], [1.0, 1.0])

    def test_excessive_detour_is_rejected_by_stretch(self):
        # WAYPOINT_MAX_STRETCH: an alternative may not exceed the best route
        # through the required stops by more than 1.5x in stops. The fragmented
        # w-chain is 12 stops against the best route's 7, so it is dropped even
        # though k=3 leaves room for it.
        paths = self.finder.k_shortest_paths("A", "B", via=["C"])
        self.assertNotIn(self.LONG_FRAGMENTED, paths)
        self.assertTrue(all(len(p) <= 7 * 1.5 for p in paths))

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


class LegScoringTests(SimpleTestCase):
    """How a required stop divides the trip, and how the divided trip is scored."""

    def test_a_plain_query_is_one_leg_spanning_the_whole_chain(self):
        # Callers (views.path, the find_route command, the UI) read `legs`
        # unconditionally, so a query with no required stops has to be a one-leg trip
        # rather than an empty list — and that one leg must report exactly what the
        # route reports, since the weighted mean over a single leg is the identity.
        finder = RouteFinder(Graph.from_routes(SPEC_ROUTES))
        for route in finder.find_routes("K", "M"):
            self.assertEqual(len(route.legs), 1)
            leg = route.legs[0]
            self.assertEqual((leg.start_index, leg.end_index), (0, route.total_hops))
            self.assertEqual(leg.hhi, route.hhi)
            self.assertEqual(leg.priority, route.priority)
            self.assertEqual(list(leg.runs), route.runs)

    def test_legs_tile_the_chain(self):
        # Adjacent legs share their boundary node — the required stop itself — and
        # together they cover the chain exactly. The API hands these indices to the
        # UI to slice `paths[i]` with, so a gap or an overlap would drop or duplicate
        # a stop on screen.
        finder = RouteFinder(Graph.from_routes(WaypointTests.WAYPOINT_ROUTES))
        for route in finder.find_routes("A", "B", via=["P"]):
            self.assertEqual(route.legs[0].start_index, 0)
            self.assertEqual(route.legs[-1].end_index, route.total_hops)
            for before, after in zip(route.legs, route.legs[1:]):
                self.assertEqual(before.end_index, after.start_index)

    def test_trip_concentration_is_the_legs_length_weighted_mean(self):
        # The defining identity, asserted over whatever shapes the pool produces.
        for routes_def, start, end, via in (
            (WaypointTests.WAYPOINT_ROUTES, "A", "B", ["P"]),
            (WaypointTests.SPUR_STOP_ROUTES, "S", "T", ["W"]),
            (WaypointTests.THROUGH_STOP_ROUTES, "S", "T", ["V"]),
        ):
            finder = RouteFinder(Graph.from_routes(routes_def))
            for route in finder.find_routes(start, end, via=via):
                lengths = [sum(run.length for run in leg.runs) for leg in route.legs]
                total = sum(lengths)
                expected = (
                    sum(l / total * leg.hhi for l, leg in zip(lengths, route.legs))
                    if total
                    else sum(leg.hhi for leg in route.legs) / len(route.legs)
                )
                self.assertAlmostEqual(route.hhi, expected, msg=str(route.stops))

    def test_credit_does_not_pool_across_a_required_stop(self):
        # The concrete difference from scoring the chain undivided. A-B-C rides one
        # road; C-D-E transfers halfway. Leg-wise that is a perfect leg and an evenly
        # split one — (2/4)·1.0 + (2/4)·0.5 = 0.75. Undivided, the same chain is three
        # runs of 2/1/1 hops against a 4-hop total, i.e. 0.375: the first road's stint
        # gets diluted by roads the driver only takes *after* stopping at C. Which of
        # the two is right is the whole question a required stop answers.
        with length_mode(False):
            graph = Graph.from_routes([["A", "B", "C"], ["C", "D"], ["D", "E"]])
            routes = RouteFinder(graph).find_routes("A", "E", via=["C"])
            self.assertTrue(routes)
            best = routes[0]
            self.assertEqual(best.stops, ["A", "B", "C", "D", "E"])
            self.assertEqual([leg.hhi for leg in best.legs], [1.0, 0.5])
            self.assertAlmostEqual(best.hhi, 0.75)
            self.assertAlmostEqual(evaluate(graph, best.stops)[0], 0.375)

    def test_zero_length_trip_still_scores(self):
        # Under CROSSROADS_ONLY a trip can measure zero length — nothing on it is a
        # junction. Every leg then weighs nothing, so the weighted mean is undefined
        # and falls back to the plain mean, mirroring evaluate()'s own L == 0 branch.
        # Weighting anyway would hand a zero-length leg zero weight, which lets a
        # route wander through transparent nodes as though that stretch were not part
        # of the trip at all.
        graph = Graph.from_routes([["A", "B"], ["B", "C"]])
        self.assertEqual(graph.crossroads(), [])
        routes = RouteFinder(graph).find_routes("A", "C", via=["B"])
        self.assertTrue(routes, "no route through a trip that crosses no junction")
        self.assertEqual(routes[0].stops, ["A", "B", "C"])
        self.assertAlmostEqual(routes[0].hhi, 1.0)


class TransparencyTests(SimpleTestCase):
    """Nodes with <=2 connections are transparent: under CROSSROADS_ONLY, only
    crossroads count toward the ranking length reference."""

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
        # Under CROSSROADS_ONLY, a long transparent chain A..B is ONE
        # crossroad-to-crossroad hop, so it beats the two-hop route through
        # crossroad M -- even though it has far more nodes. The ranking's length
        # reference follows the active LengthMode (matching what evaluate() sums
        # for the HHI itself), so under the default plain-hop-count mode the
        # shorter M route wins instead -- raw hops is exactly the unit that mode
        # says "length" means.
        graph = Graph.from_routes(
            [
                ["A", "l1", "l2", "l3", "l4", "l5", "B"],  # long transparent road
                ["A", "M", "B"],                            # short road via crossroad M
                ["A", "a2"], ["B", "b2"], ["M", "m2"],      # make A, B, M crossroads
            ]
        )
        finder = RouteFinder(graph)

        with length_mode(False):
            default_paths = finder.k_shortest_paths("A", "B", k=3)
        self.assertEqual(default_paths[0], ["A", "M", "B"])
        self.assertIn(["A", "l1", "l2", "l3", "l4", "l5", "B"], default_paths)

        with length_mode(True):
            crossroad_paths = finder.k_shortest_paths("A", "B", k=3)
        self.assertEqual(crossroad_paths[0], ["A", "l1", "l2", "l3", "l4", "l5", "B"])
        self.assertIn(["A", "M", "B"], crossroad_paths)

        for p in default_paths + crossroad_paths:
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

        # A-B-R-G merges two routes and reports it — verified on the ranked pool,
        # since the ALTERNATIVE_FLOOR now trims it from the shown results: its
        # concentration (hhi 0.56) is below 0.70 * the perfect headline (1.0), i.e.
        # it is exactly the "when #1 is an absolute match, the alternative is junk"
        # case the floor is there to drop.
        ranked, _ = finder.rank_candidates("A", "G")
        alt = next(r for r in ranked if r.stops == ["A", "B", "R", "G"])
        self.assertEqual(alt.route_count, 2)
        self.assertEqual(alt.route_ids, [0, 1])
        self.assertNotIn(["A", "B", "R", "G"], [r.stops for r in routes])

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
        # A->R: both corridors merge 2 routes, so concentration decides. Counting
        # every hop, [A, L, K, J, E, R] rides route 2 for 4 of its 5 hops (80%),
        # against 5 of 7 (71%) for the A-B-C-M-N-G-E-R corridor, so it wins.
        # (Crossroads-only it was the balanced 50/50 one and the other corridor
        # won — the expected winner follows the length mode, the property under
        # test does not.)
        with length_mode(False):
            routes = self.finder.find_routes("A", "R", k=3)
        best = routes[0]
        self.assertEqual(best.stops, ["A", "L", "K", "J", "E", "R"])
        self.assertEqual(best.route_count, 2)
        self.assertIn(["A", "B", "C", "M", "N", "G", "E", "R"], [r.stops for r in routes])
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
# (routes 1, 2) — three merged routes but far more concentrated — and a balanced
# two-route blend (routes 6, 7). Stubs make the interior nodes crossroads.
#
# The artery is long enough that it dominates under *either* length mode: with
# crossroads-only the brief end-hops are length-0 and it scores a perfect 1.0;
# counting every hop they weigh in, but 6 hops of artery against one hop in and
# one hop out still beats the 50/50 blend. New stubs go on the end so the earlier
# routes keep their indices (tests assert on `route_id`).
CONCENTRATION_ROUTES = [
    ["x", "a1", "a2", "a3", "a4", "a5", "y"],   # 0: the artery
    ["S", "x"],                      # 1: entry hop onto the artery
    ["y", "T"],                      # 2: exit hop off the artery
    ["a1", "p1"],                    # 3: stub -> a1 becomes a crossroad
    ["a2", "p2"],                    # 4: stub -> a2 crossroad
    ["a3", "p3"],                    # 5: stub -> a3 crossroad
    ["S", "b1", "m"],                # 6: balanced corridor, first half
    ["m", "b2", "T"],                # 7: balanced corridor, second half
    ["b1", "q1"],                    # 8: stub -> b1 crossroad
    ["b2", "q2"],                    # 9: stub -> b2 crossroad
    ["a4", "p4"],                    # 10: stub -> a4 crossroad
    ["a5", "p5"],                    # 11: stub -> a5 crossroad
]

ARTERY = ["x", "a1", "a2", "a3", "a4", "a5", "y"]
CORRIDOR_A = ["S", *ARTERY, "T"]          # merges 3, HHI 38/64 (1.0 crossroads-only)
CORRIDOR_B = ["S", "b1", "m", "b2", "T"]  # merges 2, HHI 0.5


class ConcentrationTests(SimpleTestCase):
    """"Best" = riding one authored route as far as possible (max concentration)."""

    def setUp(self):
        self.graph = Graph.from_routes(CONCENTRATION_ROUTES)
        self.finder = RouteFinder(self.graph)

    def test_evaluate_single_route_is_perfect(self):
        hhi, runs = evaluate(self.graph, ARTERY)
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
        # Only reachable under crossroads-only lengths — counting every hop, a
        # chain of >= 2 stops always has length — so the mode is pinned here
        # rather than left to the default, or the fallback goes untested.
        g = Graph.from_routes([["X", "A", "B"], ["B", "C", "Y"]])
        with length_mode(True):
            hhi, runs = evaluate(g, ["X", "A", "B", "C", "Y"])
        self.assertAlmostEqual(hhi, 0.5)
        self.assertEqual(sorted({r.route_id for r in runs}), [0, 1])

    def test_best_maximises_concentration_even_with_more_merges(self):
        # Non-monotonic: the 3-route artery corridor (HHI 38/64) beats the
        # balanced 2-route blend (HHI 0.5) — best may merge MORE routes, and be
        # the longer route, to stay concentrated.
        routes = self.finder.find_routes("S", "T", k=3)
        self.assertEqual(routes[0].stops, CORRIDOR_A)
        self.assertAlmostEqual(routes[0].hhi, 38 / 64)
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
        # Both modes are asserted explicitly, and the flag is restored to
        # whatever it *was* — hardcoding the restore silently rewrites the
        # default for every test that runs after this one.
        with length_mode(True):
            self.assertAlmostEqual(evaluate(self.graph, CORRIDOR_A)[0], 1.0)
        with length_mode(False):
            # runs of 1, 6 and 1 hops -> (1 + 36 + 1) / 64
            self.assertAlmostEqual(evaluate(self.graph, CORRIDOR_A)[0], 38 / 64)

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


def whole_chain_marks(routes, priorities):
    """The marks equivalent to the per-route ``priority`` field marks replaced.

    One mark spanning each route end to end — exactly what :func:`~api.db.
    upgrade_node` writes for a flat route authored before marks existed, and the
    shortest way for a fixture to say "this whole artery is rated p". A chain that
    rides such an artery end to end completes the mark, so these fixtures downgrade
    just as the old field always did; a chain that only clips it does not, which is
    the new behaviour :class:`PriorityMarkContainmentTests` pins down.
    """
    return [
        [(route[0], route[-1], priority)] if priority and len(route) >= 2 else []
        for route, priority in zip(routes, priorities)
    ]


# Two S->T corridors that put the tier and the score in direct conflict:
#   * the "patchwork" [S, c1, c2, c3, T] stitches four *well-rated* routes — poorly
#     concentrated (it transfers at every stop) but never leaves priority 0.
#   * the "clean ride" [S, q1, q2, q3, T] is a single artery end to end — perfectly
#     concentrated, and shorter — but that artery is rated below best. The ride
#     covers the artery's mark whole, so the downgrade bites — see
#     PriorityMarkContainmentTests for a ride that only clips one.
# Stubs (routes 5..10) make the interior nodes crossroads so they carry length.
PRIORITY_ROUTES = [
    ["S", "c1"],              # 0: patchwork, leg 1
    ["c1", "c2"],             # 1: patchwork, leg 2
    ["c2", "c3"],             # 2: patchwork, leg 3
    ["c3", "T"],              # 3: patchwork, leg 4
    ["S", "q1", "q2", "q3", "T"],   # 4: the clean single artery
    ["c1", "z1"],             # 5..10: stubs -> the interior nodes are crossroads
    ["c2", "z2"],
    ["c3", "z3"],
    ["q1", "z4"],
    ["q2", "z5"],
    ["q3", "z6"],
]
# Only the clean artery is downgraded, over its whole length; every other route
# stays best-priority.
DOWNGRADED_ARTERY = whole_chain_marks(
    PRIORITY_ROUTES, [0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0]
)

PATCHWORK = ["S", "c1", "c2", "c3", "T"]         # tier 0, score 0.25 — badly concentrated
CLEAN_RIDE = ["S", "q1", "q2", "q3", "T"]        # tier 1, score 1.0 — but poorly rated


class ArteryPairTests(SimpleTestCase):
    """A corridor made of *two* long arteries in sequence must reach the pool.

    Biasing toward one artery fills everything around it with whatever is
    shortest, not whatever is most concentrated — an off-artery edge and a route
    transfer cost the same in the generator. So each artery's own pass pairs it
    with the cheap fragmented filler, and the corridor that rides both never gets
    proposed. This is the live ``מחסום בזק -> צאלים via צ. רבדים`` case, boiled
    down to the smallest network that reproduces it.
    """

    # S -> M by one long road (A, 6 hops) or a short fragmented pair (P+Q, 4);
    # M -> E by a long trunk plus tail (T 8 + L 2) or four one-hop scraps (r1..r4).
    PAIR_ROUTES = [
        ["S", "a1", "a2", "a3", "a4", "a5", "M"],              # 0: A, the long approach
        ["S", "p1", "X"],                                      # 1: P }  short but
        ["X", "q1", "M"],                                      # 2: Q }  fragmented
        ["M", "t1", "t2", "t3", "t4", "t5", "t6", "t7", "N"],  # 3: T, the trunk
        ["N", "l1", "E"],                                      # 4: L, the tail
        ["M", "y1"],                                           # 5..8: four scraps,
        ["y1", "y2"],                                          #       short but as
        ["y2", "y3"],                                          #       fragmented as
        ["y3", "E"],                                           #       it gets
    ]
    #      A + T + L : (6² + 8² + 2²) / 16² = 0.406  <- most concentrated
    #      P + Q + T + L : (2² + 2² + 8² + 2²) / 14² = 0.388   (what prefer(T) finds)
    #      A + r1..r4 : (6² + 1 + 1 + 1 + 1) / 10²  = 0.400    (what prefer(A) finds)
    PAIRED = ["S", "a1", "a2", "a3", "a4", "a5", "M",
              "t1", "t2", "t3", "t4", "t5", "t6", "t7", "N", "l1", "E"]

    def setUp(self):
        self.finder = RouteFinder(Graph.from_routes(self.PAIR_ROUTES))

    def test_two_artery_corridor_is_generated(self):
        ranked, _ = self.finder.rank_candidates("S", "E")
        self.assertIn(self.PAIRED, [r.stops for r in ranked])

    def test_two_artery_corridor_is_the_most_concentrated(self):
        # It is not merely present — it is the best-concentrated thing in the pool,
        # which is what makes its absence a real loss rather than a missing extra.
        ranked, _ = self.finder.rank_candidates("S", "E")
        best = max(ranked, key=lambda r: r.hhi)
        self.assertEqual(best.stops, self.PAIRED)
        self.assertEqual(best.route_count, 3)  # A, T, L — no fragmented filler

    def test_single_artery_passes_alone_would_miss_it(self):
        # The premise: neither one-artery bias proposes this corridor, so the pool
        # would not contain it without the pair pass. Guards the test from quietly
        # passing for the wrong reason if generation changes.
        graph = self.finder.graph
        for route_id in (0, 3):  # A and T, the two arteries it rides
            nodes, _ = MinMergeStrategy(graph, "S", "E").find(
                prefer_route_penalty(graph, route_id)
            )
            self.assertNotEqual(nodes, self.PAIRED)


class PriorityTests(SimpleTestCase):
    """Priority is a hard tier over the concentration score: the worst mark a route
    is forced to complete outranks how well it rides anything."""

    def setUp(self):
        self.graph = Graph.from_routes(PRIORITY_ROUTES, DOWNGRADED_ARTERY)
        self.finder = RouteFinder(self.graph)

    def test_score_ignores_the_rating_of_the_artery_ridden(self):
        # Riding one priority-1 artery end to end is a perfect *ride*, so it scores
        # 1.0: the score says how concentrated the ride is, never how well-rated the
        # artery is. That the artery is priority-1 shows up as the tier below, which
        # is the only place a rating is allowed to speak.
        score, runs = evaluate(self.graph, CLEAN_RIDE)
        self.assertAlmostEqual(score, 1.0)
        self.assertEqual([r.route_id for r in runs], [4])
        self.assertEqual([r.priority for r in runs], [1])

    def test_best_priority_artery_still_scores_a_perfect_one(self):
        # The weighting must not move the ceiling: an unrated artery still hits 1.0.
        graph = Graph.from_routes(PRIORITY_ROUTES)  # nothing downgraded
        self.assertAlmostEqual(evaluate(graph, CLEAN_RIDE)[0], 1.0)

    def test_tier_is_the_worst_mark_the_chain_must_complete(self):
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
        # hhi is priority-free: riding one artery end to end is a perfect 1.0 however
        # that artery is rated. Its priority-1 rating shows up as the tier, which is
        # why this corridor is the fall-through alternative and not the headline.
        self.assertAlmostEqual(routes[1].hhi, 1.0)

    def test_soft_mode_lets_the_better_route_win(self):
        # Drop the tier from the ranking and concentration alone decides, so the
        # clean (if poorly-rated) ride takes the lead. Note hhi carries no priority
        # of its own, so with the arena off nothing else does either: this flag now
        # makes the ranking fully priority-blind, not merely priority-softened.
        PriorityMode.HARD_TIER = False
        try:
            routes = self.finder.find_routes("S", "T", k=3)
        finally:
            PriorityMode.HARD_TIER = True
        self.assertEqual(routes[0].stops, CLEAN_RIDE)
        self.assertAlmostEqual(routes[0].hhi, 1.0)

    def test_avoid_priority_penalty_finds_the_tier_clean_corridor(self):
        # The generator pass that puts the patchwork in the pool at all: confined to
        # priority-0 arteries, the only way from S to T is the long way round.
        strategy = MinMergeStrategy(self.graph, "S", "T")
        nodes, _ = strategy.find(avoid_priority_penalty(self.graph, 0))
        self.assertEqual(nodes, PATCHWORK)
        # Unconstrained, the same search takes the clean (downgraded) artery — which
        # is exactly why the tier-clean corridor needs a pass of its own.
        self.assertEqual(strategy.find({})[0], CLEAN_RIDE)


class PriorityMarkContainmentTests(SimpleTestCase):
    """A mark rates a *stretch*, and only a run that rides it **whole** pays.

    This is what replaced the old length exemption: how much of an artery has to be
    driven before its rating applies is drawn by the author, not guessed from a
    constant. Clipping a marked stretch — even by a single edge — is free.
    """

    # One long artery, rated only between C and F.
    ARTERY = ["A", "B", "C", "D", "E", "F", "G"]
    MARKS = [[("C", "F", 2)]]

    def setUp(self):
        self.graph = Graph.from_routes([self.ARTERY], self.MARKS)

    def test_a_ride_covering_the_mark_pays_for_it(self):
        chain = ["B", "C", "D", "E", "F", "G"]
        self.assertEqual(tier(self.graph, chain), 2)
        _, runs = evaluate(self.graph, chain)
        self.assertEqual([r.priority for r in runs], [2])

    def test_a_ride_one_edge_short_of_the_mark_is_free(self):
        # Stops at E: the whole stretch C..F is not covered, so nothing is owed.
        for chain in (["A", "B", "C", "D", "E"], ["D", "E", "F", "G"]):
            self.assertEqual(tier(self.graph, chain), 0)

    def test_riding_the_whole_artery_pays_too(self):
        # More than the mark still contains the mark.
        self.assertEqual(tier(self.graph, self.ARTERY), 2)

    def test_containment_is_direction_independent(self):
        chain = ["B", "C", "D", "E", "F", "G"]
        self.assertEqual(tier(self.graph, chain), tier(self.graph, chain[::-1]))

    def test_the_worst_completed_mark_wins(self):
        # Two marks on one artery: a chain covering both is rated by the worse one,
        # and a chain covering only the milder one is rated by that.
        graph = Graph.from_routes(
            [["A", "B", "C", "D", "E", "F", "G", "H", "I"]],
            [[("B", "C", 1), ("F", "H", 3)]],
        )
        self.assertEqual(tier(graph, ["A", "B", "C", "D"]), 1)
        self.assertEqual(tier(graph, ["E", "F", "G", "H"]), 3)
        self.assertEqual(tier(graph, ["A", "B", "C", "D", "E", "F", "G", "H"]), 3)

    def test_an_unmarked_artery_is_never_downgraded(self):
        graph = Graph.from_routes([self.ARTERY])
        self.assertEqual(tier(graph, self.ARTERY), 0)
        self.assertFalse(graph.has_priorities())


class PriorityTierFollowsRiddenRouteTests(SimpleTestCase):
    """The tier follows the road the chain covers — NOT an edge-only best. Where a
    marked stretch is co-served by a well-rated route, the mark still bites (see
    :class:`MarkRatesTheRoadTests`); what this class pins is the other half of that:
    the *score* is free to credit the stretch wherever it is most concentrated, and
    doing so neither creates nor clears a rating."""

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
        self.graph = Graph.from_routes(
            self.ROUTES, whole_chain_marks(self.ROUTES, self.PRIORITIES)
        )

    def test_score_credits_the_long_run_to_the_downgraded_artery(self):
        # One 6-long run on the priority-2 artery scores 36/36 = 1.0; splitting the
        # same chain across the four well-rated legs scores only 10/36 ≈ 0.28. So the
        # score-maximising assignment rides the *downgraded* artery — and the tier
        # (asserted below) is what reports that it did.
        score, runs = evaluate(self.graph, self.CHAIN)
        self.assertAlmostEqual(score, 1.0)
        self.assertEqual([r.route_id for r in runs], [0])
        self.assertEqual([r.priority for r in runs], [2])

    def test_tier_follows_the_ridden_sub_route(self):
        # The chain rides the priority-2 artery's marked stretch whole, so the route
        # is tier 2 — even though every edge is *also* on a priority-0 route, and
        # whichever of them the credit assignment happens to pick.
        self.assertEqual(tier(self.graph, self.CHAIN), 2)
        # The per-edge best is still 0 — that's what generation uses to hunt for a
        # physically different corridor, but it is not the route's tier.
        self.assertEqual(self.graph.edge_priority("u1", "u2"), 0)

    def test_ranking_prefers_a_genuinely_better_rated_corridor_when_one_exists(self):
        # Add a physically separate all-priority-0 detour S->d->T. It's less
        # concentrated (two arteries) but never rides the downgraded one, so hard
        # tiering puts it first and the concentrated priority-2 ride second.
        routes = self.ROUTES + [
            ["S", "d1", "d2"],
            ["d2", "d3", "T"],
            ["d1", "z8"],
            ["d2", "z9"],
        ]
        graph = Graph.from_routes(
            routes, whole_chain_marks(routes, self.PRIORITIES + [0, 0, 0, 0])
        )
        results = RouteFinder(graph).find_routes("S", "T", k=3)
        self.assertEqual(results[0].priority, 0)
        self.assertNotIn(0, results[0].route_ids)  # does not ride the downgraded artery
        self.assertEqual(results[1].priority, 2)   # the concentrated ride is still offered


class MarkRatesTheRoadTests(SimpleTestCase):
    """A mark rates the **road**, so no reading of a chain can shed one.

    The shape is the reported bug, minimised: a rated spur `P -> n1 -> T` that a
    second, unrated authored route also covers. `n1` and `T` are not crossroads, so
    the edge `n1 -> T` carries **zero** length — which used to make peeling it onto
    the unrated route free: the split tied on concentration, ended the marked run one
    edge short of the mark, and the tier read 0 for a route that drove every metre of
    the rated road. Whether a mark bites is now decided by the edges the chain
    covers, before any credit is assigned, so the dodge (and the required-stop
    variant of it) is gone.
    """

    # 0: the marked artery, rated only over its spur P..T.
    # 1: an unrated artery joining at P and covering the same spur — riding the spur
    #    "as route 1" is a real, sometimes better-concentrated reading of the road.
    ROUTES = [
        ["H", "g1", "g2", "P", "n1", "T"],
        ["Q", "P", "n1", "T"],
        ["g1", "z1"],   # stubs -> g1/g2 are crossroads and carry length,
        ["g2", "z2"],   # while n1 (degree 2) and T (degree 1) carry none
    ]
    MARKS = [[("P", "T", 3)], [], [], []]
    APPROACH = ["H", "g1", "g2", "P", "n1", "T"]

    def setUp(self):
        self.graph = Graph.from_routes(self.ROUTES, self.MARKS)
        # The premise: the spur's last edge is weightless, so splitting a run there
        # costs the score exactly nothing.
        self.assertEqual(edge_unit(self.graph, "n1", "T"), 0)

    def test_a_weightless_transfer_cannot_shed_the_mark(self):
        # The whole approach is one run on the marked artery. Peeling the free last
        # edge onto route 1 would once have made this tier 0.
        self.assertEqual(tier(self.graph, self.APPROACH), 3)
        score, runs = evaluate(self.graph, self.APPROACH)
        self.assertAlmostEqual(score, 1.0)
        self.assertEqual([r.priority for r in runs], [3])

    def test_the_free_transfer_is_not_taken_at_all(self):
        # Ties on concentration now go to the fewest transfers, so the reported ride
        # is the plain one — no run that rides nothing.
        _, runs = evaluate(self.graph, self.APPROACH)
        self.assertEqual([r.route_id for r in runs], [0])

    def test_crediting_a_co_serving_route_does_not_shed_the_mark(self):
        # Q -> T rides the spur most concentratedly as the *unrated* route 1, and the
        # score is welcome to say so — but the rated road was still driven end to end.
        chain = ["Q", "P", "n1", "T"]
        score, runs = evaluate(self.graph, chain)
        self.assertAlmostEqual(score, 1.0)
        self.assertEqual([r.route_id for r in runs], [1])   # credited to the unrated one
        self.assertEqual([r.priority for r in runs], [3])   # and still rated
        self.assertEqual(tier(self.graph, chain), 3)

    def test_clipping_the_stretch_is_still_free(self):
        # Stopping at n1 never covers P..T, so nothing is owed — the author's line
        # between brushing past a road and riding it is untouched.
        self.assertEqual(tier(self.graph, ["H", "g1", "g2", "P", "n1"]), 0)

    def test_a_required_stop_inside_the_mark_does_not_shed_it(self):
        # n1 sits *inside* the rated spur, so scoring the trip leg by leg puts the
        # mark's two ends in different chains. The trip still rode the road.
        route = RouteFinder(self.graph).find_routes("H", "T", k=1, via=["n1"])[0]
        self.assertEqual(route.priority, 3)
        self.assertEqual(len(route.legs), 2)
        # Both legs fall across the rated stretch, so both report it.
        self.assertEqual([leg.priority for leg in route.legs], [3, 3])

    def test_an_untouched_mark_rates_nothing(self):
        # A chain nowhere near the spur is unrated, marks or no marks.
        self.assertEqual(tier(self.graph, ["z1", "g1", "g2", "z2"]), 0)


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
ARENA_MARKS = whole_chain_marks(ARENA_ROUTES, [0, 1, 0, 0, 0, 0] + [0] * 12)


class PriorityArenaTests(SimpleTestCase):
    """The priority arena surfaces a concentrated tier>0 corridor as an
    alternative once it out-concentrates the remaining same-or-lower-tier
    options — instead of the top-3 collapsing to only tier-0 routes."""

    def setUp(self):
        self.graph = Graph.from_routes(ARENA_ROUTES, ARENA_MARKS)
        self.finder = RouteFinder(self.graph)

    def test_concentrated_higher_tier_surfaces_as_alternative(self):
        results = self.finder.find_routes("S", "T", k=3)
        # #1 is the perfect tier-0 ride; #2 is the tier-1 artery, which surfaces
        # rather than the list collapsing to only tier-0 corridors. The two weak
        # tier-0 patchworks (hhi 0.5) that used to fill the third slot are now
        # trimmed by ALTERNATIVE_FLOOR — 0.5 is below the floor times the perfect
        # headline — so the arena and the floor together yield "the clean ride + the
        # clean tier-1 artery", dropping the junk. The tier-1 alternative rides its
        # artery end to end, so its priority-free hhi is a perfect 1.0 too; what
        # separates the two corridors is the tier, which is exactly what the arena
        # ranks on.
        self.assertEqual([r.priority for r in results], [0, 1])
        self.assertAlmostEqual(results[0].hhi, 1.0)
        self.assertAlmostEqual(results[1].hhi, 1.0)
        self.assertEqual(results[1].stops, ["S", "q1", "q2", "q3", "T"])

    def test_headline_is_still_the_best_tier_zero_route(self):
        # The arena never demotes the genuine best: round one admits only tier 0.
        results = self.finder.find_routes("S", "T", k=3)
        self.assertEqual(results[0].stops, ["S", "a1", "a2", "a3", "T"])
        self.assertEqual(results[0].priority, 0)


# The arena's situation, inverted, sitting inside a trip's *second leg*: that leg's
# most concentrated corridor is the downgraded one (a single tier-2 artery, hhi 1.0),
# and its clean tier-0 corridor is fragmented enough (hhi ~0.51) to fall below
# ALTERNATIVE_FLOOR of it. Pick each leg by concentration alone and the tier-0
# corridor is gone before the whole-route arena ever runs, so the trip can only be
# assembled at tier 2 — even though a tier-0 trip plainly exists.
LEG_ARENA_ROUTES = [
    ["P", "p1", "S"],               # 0: the first leg, one clean artery
    ["S", "q1", "q2", "q3", "T"],   # 1: leg 2's downgraded artery      -> hhi 1.0
    ["S", "b1", "b2"],              # 2..3: leg 2's clean but fragmented corridor
    ["b2", "b3", "T"],
    # stubs so every interior node is a real crossroad (carries length)
    ["p1", "zp1"],
    ["q1", "zq1"], ["q2", "zq2"], ["q3", "zq3"],
    ["b1", "zb1"], ["b2", "zb2"], ["b3", "zb3"],
]
LEG_ARENA_MARKS = whole_chain_marks(LEG_ARENA_ROUTES, [0, 2, 0, 0] + [0] * 7)


class LegPriorityArenaTests(SimpleTestCase):
    """The priority arena has to hold for a *leg* exactly as it holds for a whole
    route — which is why a leg's candidates are picked by `select_diverse` itself
    rather than by a cheaper filter of its own."""

    def setUp(self):
        self.finder = RouteFinder(Graph.from_routes(LEG_ARENA_ROUTES, LEG_ARENA_MARKS))

    def test_a_leg_offers_its_clean_corridor_even_when_it_scores_worse(self):
        # Round one of the arena admits only tier 0, so the leg's clean corridor is
        # taken first however poorly it scores, and the downgraded one follows behind
        # once the arena widens. Both have to survive: the first is the only way to
        # build a tier-0 trip, the second the only way to build the concentrated one.
        pool = self.finder._leg_candidates("S", "T", [])
        self.assertEqual([r.priority for r in pool], [0, 2])
        self.assertLess(pool[0].q, pool[1].q)  # the clean corridor is the *weaker* one

    def test_the_trip_headline_is_the_best_tier_zero_route(self):
        results = self.finder.find_routes("P", "T", via=["S"])
        self.assertEqual(results[0].priority, 0)
        self.assertEqual(results[0].stops, ["P", "p1", "S", "b1", "b2", "b3", "T"])
        # ...and the concentrated tier-2 trip is still offered, once the arena opens
        # to its tier — priority ranks, it never filters.
        self.assertEqual([r.priority for r in results], [0, 2])
        self.assertGreater(results[1].q, results[0].q)

    def test_the_arena_is_dropped_with_hard_tier_off(self):
        # Leg selection tracks PriorityMode exactly as whole-route selection does:
        # with the tier gate off, both levels are plain concentration-first, so the
        # downgraded corridor leads its leg and the trip.
        previous = PriorityMode.HARD_TIER
        PriorityMode.HARD_TIER = False
        try:
            pool = self.finder._leg_candidates("S", "T", [])
            self.assertEqual(pool[0].priority, 2)
            results = self.finder.find_routes("P", "T", via=["S"])
            self.assertEqual(results[0].stops, ["P", "p1", "S", "q1", "q2", "q3", "T"])
        finally:
            PriorityMode.HARD_TIER = previous


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

    def test_explicit_best_priority_marks_are_still_no_priorities(self):
        # Passing all-zeroes is the same as passing nothing — the common case once
        # a caller hands in marks that all rate at the default.
        graph = Graph.from_routes(
            SPEC_ROUTES, [[(route[0], route[-1], 0)] for route in SPEC_ROUTES]
        )
        self.assertFalse(graph.has_priorities())
        self.assertEqual(graph.route_marks(0), ())

    def test_unrated_graph_scores_exactly_as_before(self):
        graph = Graph.from_routes(SPEC_ROUTES)
        routes = RouteFinder(graph).find_routes("K", "M", k=3)
        self.assertEqual(routes[0].stops, ["K", "J", "E", "G", "N", "M"])
        self.assertEqual(routes[0].priority, 0)


class RoutePriorityStorageTests(R2BackedTestCase):
    """routes.json stores {places, marks}; the shapes that predate marks — a bare
    place list, and a whole-route ``priority`` — still load, upgraded."""

    MARK = {"from": 1, "to": 3, "priority": 2}
    CHAIN = ["A", "B", "C", "D", "E"]

    def test_saves_and_loads_marks(self):
        saved = self.db.save_routes(
            [{"places": self.CHAIN, "marks": [self.MARK]}, {"places": ["E", "F"]}]
        )
        self.assertEqual(saved[0], {"places": self.CHAIN, "marks": [self.MARK]})
        # An unmarked route carries no `marks` key at all.
        self.assertEqual(saved[1], {"places": ["E", "F"]})
        self.assertEqual(self.db.load_routes(), saved)
        # Indices become place ids on the way into the graph (internal identity
        # since the ID-registry migration — see api.db's module docstring).
        self.assertEqual(self.db.load_graph().route_marks(0), ((self.id("B"), self.id("D"), 2),))

    def test_marks_are_sorted_and_overlap_is_rejected(self):
        saved = self.db.save_routes(
            [
                {
                    "places": self.CHAIN,
                    "marks": [
                        {"from": 3, "to": 4, "priority": 1},
                        {"from": 0, "to": 1, "priority": 3},
                    ],
                }
            ]
        )
        self.assertEqual([m["from"] for m in saved[0]["marks"]], [0, 3])
        # Meeting at a stop shares no edge, so it is allowed …
        self.db.save_routes(
            [
                {
                    "places": self.CHAIN,
                    "marks": [
                        {"from": 0, "to": 2, "priority": 1},
                        {"from": 2, "to": 4, "priority": 3},
                    ],
                }
            ]
        )
        # … sharing one is not.
        with self.assertRaises(ValidationError):
            self.db.save_routes(
                [
                    {
                        "places": self.CHAIN,
                        "marks": [
                            {"from": 0, "to": 2, "priority": 1},
                            {"from": 1, "to": 4, "priority": 1},
                        ],
                    }
                ]
            )

    def test_rejects_marks_outside_the_chain_or_spanning_no_edge(self):
        for bad in (
            {"from": 0, "to": 5, "priority": 1},   # past the last stop
            {"from": -1, "to": 2, "priority": 1},  # before the first
            {"from": 2, "to": 2, "priority": 1},   # a single stop is not a ride
            {"from": 3, "to": 1, "priority": 1},   # backwards
            {"from": 0, "to": 1, "priority": 0},   # says nothing an unmarked stretch doesn't
            {"from": 0, "to": 1, "priority": 4},   # out of range
            {"from": "0", "to": 1, "priority": 1},
            {"from": True, "to": 1, "priority": 1},
        ):
            with self.assertRaises(ValidationError):
                self.db.save_routes([{"places": self.CHAIN, "marks": [bad]}])

    def test_legacy_bare_lists_load_unmarked(self):
        # Written before priorities existed; must still load, and be upgraded on save.
        self.db.save_routes([["A", "B", "C"]])
        self.assertEqual(self.db.load_routes(), [{"places": ["A", "B", "C"]}])
        self.assertFalse(self.db.load_graph().has_priorities())

    def test_legacy_priority_upgrades_to_a_corridor_mark(self):
        saved = self.db.save_routes([{"places": ["A", "B", "C"], "priority": 2}])
        self.assertEqual(
            saved, [{"places": ["A", "B", "C"], "marks": [{"from": 0, "to": 2, "priority": 2}]}]
        )
        # And it bites exactly where it used to: on a ride of the whole artery.
        graph = self.db.load_graph()
        self.assertEqual(tier(graph, self.ids(["A", "B", "C"])), 2)
        self.assertEqual(tier(graph, self.ids(["A", "B"])), 0)

    def test_a_route_stating_marks_ignores_a_legacy_priority(self):
        # Marks are the more specific statement; the deprecated field must not add
        # a second, whole-chain rating on top of them.
        saved = self.db.save_routes(
            [{"places": self.CHAIN, "priority": 3, "marks": [self.MARK]}]
        )
        self.assertEqual(saved[0]["marks"], [self.MARK])

    def test_marks_survive_the_derived_graph_rebuild(self):
        # Marks live only in routes.json — edge_routes.json never carries them, so
        # this proves they're re-attached on load rather than lost.
        self.db.save_routes([{"places": ["A", "B", "C"], "priority": 3}])
        graph = self.db.load_graph()
        self.assertEqual(graph.edge_priority(self.id("A"), self.id("B")), 3)
        self.assertEqual(graph.worst_priority(), 3)

    def test_routable_graph_keeps_marks(self):
        self.db.save_routes(
            [{"places": ["A", "B", "C"], "priority": 2}, {"places": ["C", "D"]}]
        )
        self.db.save_compromised([["D"]])
        self.assertEqual(self.db.load_routable_graph().route_priority(0), 2)

    def test_rejects_out_of_range_priority(self):
        with self.assertRaises(ValidationError):
            self.db.save_routes([{"places": ["A", "B"], "priority": 4}])
        with self.assertRaises(ValidationError):
            self.db.save_routes([{"places": ["A", "B"], "priority": -1}])

    def test_rejects_non_integer_priority(self):
        # `None` is absent, not invalid — it means "states none", at the root as
        # much as on a head.
        for bad in ("1", 1.5, True):
            with self.assertRaises(ValidationError):
                self.db.save_routes([{"places": ["A", "B"], "priority": bad}])

    def test_a_mark_reaches_routing_and_only_bites_on_a_ride_that_covers_it(self):
        # The whole pipeline in one assertion pair: saved as stop indices, derived
        # into edges, re-attached as place names on load, and read by the router.
        self.db.save_routes(
            [
                {
                    "places": ["S", "q1", "q2", "q3", "T"],
                    "marks": [{"from": 1, "to": 3, "priority": 2}],
                }
            ]
        )
        finder = RouteFinder(self.db.load_graph())
        self.assertEqual(finder.find_routes(self.id("q1"), self.id("q3"), k=1)[0].priority, 2)
        self.assertEqual(finder.find_routes(self.id("S"), self.id("q1"), k=1)[0].priority, 0)


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
        self.assertEqual(self.db.compromised_places(), set(self.ids(["B", "D", "E"])))

    def test_rejects_unknown_destination(self):
        with self.assertRaises(ValidationError):
            self.db.save_compromised([["ZZZ"]])

    def test_rejects_empty_group(self):
        with self.assertRaises(ValidationError):
            self.db.save_compromised([[]])

    def test_routable_graph_excludes_compromised_places(self):
        self.db.save_compromised([["C"]])
        graph = self.db.load_routable_graph()
        self.assertNotIn(self.id("C"), graph)
        self.assertIn(self.id("A"), graph)
        self.assertIn(self.id("D"), graph)

    def test_full_graph_still_includes_compromised_places(self):
        self.db.save_compromised([["C"]])
        graph = self.db.load_graph()
        self.assertIn(self.id("C"), graph)

    def test_routing_avoids_compromised_destination(self):
        self.db.save_compromised([["C"]])
        graph = self.db.load_routable_graph()
        finder = RouteFinder(graph)
        # C was the only link between the two routes' halves, so it's now
        # unreachable and A-E has no route.
        self.assertEqual(finder.k_shortest_paths(self.id("A"), self.id("E")), [])


class DetourNoticeTests(R2BackedTestCase):
    """The compromised split in views.path: one ranked pool (a single sort),
    selected twice — the natural best (to report which compromised destinations
    the top-N would have used) and the best avoiding them (the real response)."""

    TOP_N = 3

    def setUp(self):
        super().setUp()
        self.db.save_routes([["A", "B", "C"], ["C", "D", "E"]])

    def _split(self, start, end):
        """Mirror views.path: rank once, select natural + compromised-free.

        Takes/returns display-name strings (like the API); resolution to the
        graph's internal ids is purely internal here, same as views.path does.
        """
        finder = RouteFinder(self.db.load_graph())
        compromised = self.db.compromised_places()
        ranked, stretch = finder.rank_candidates(self.id(start), self.id(end))
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
        return (
            [self.names(r.stops) for r in clean],
            self.names(detour),
            [self.names(r.stops) for r in natural],
        )

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


class PlaceRegistryTests(R2BackedTestCase):
    """places.json: the {id: {name, group}} registry, and the id-resolution
    layer in save_routes/save_compromised that keeps it entirely internal —
    the wire (save_routes' input/output, load_routes, load_compromised) never
    sees a raw id, only the full display-name string it always has."""

    def test_new_places_get_distinct_ids_by_parsed_group_and_base(self):
        # The exact real-world case that broke an earlier {base_name: group}
        # design: "מ. גולני" and "מחלף גולני" are two different, genuinely
        # distinct places (a camp and an interchange) that share a base name
        # once you strip their prefix — resolving by the parsed (group, base)
        # pair, not the base alone, is what keeps them distinct here.
        saved = self.db.save_routes([["מ. גולני", "מחלף גולני"]])
        self.assertEqual(saved, [{"places": ["מ. גולני", "מחלף גולני"]}])

        camp_id, interchange_id = self.id("מ. גולני"), self.id("מחלף גולני")
        self.assertIsNotNone(camp_id)
        self.assertIsNotNone(interchange_id)
        self.assertNotEqual(camp_id, interchange_id)

        registry = self.db.load_place_registry()
        self.assertEqual(registry[camp_id], {"name": "גולני", "group": "camp"})
        self.assertEqual(registry[interchange_id], {"name": "גולני", "group": "interchange"})

    def test_unrecognized_prefix_defaults_to_other(self):
        self.db.save_routes([["אילת", "חיפה"]])
        self.assertEqual(self.db.load_place_registry()[self.id("אילת")]["group"], DEFAULT_GROUP)

    def test_load_routes_roundtrips_display_strings_byte_for_byte(self):
        routes = [
            {
                "places": ["מ. גולני", "מחלף גולני", "אילת"],
                "marks": [{"from": 0, "to": 1, "priority": 2}],
            }
        ]
        saved = self.db.save_routes(routes)
        self.assertEqual(saved, routes)
        self.assertEqual(self.db.load_routes(), routes)

    def test_resolving_tolerates_spacing_variance_in_the_prefix(self):
        # "מ.גולני" (no space) and "מ. גולני" (space) parse to the same
        # (group, base) pair, so re-adding the "same" place with slightly
        # different spacing must reuse its id rather than mint a duplicate.
        self.db.save_routes([["מ. גולני", "X"]])
        first_id = self.id("מ. גולני")
        self.db.save_routes([["מ.גולני", "X", "Y"]])
        self.assertEqual(self.id("מ.גולני"), first_id)
        camps = [e for e in self.db.load_place_registry().values() if e["group"] == "camp"]
        self.assertEqual(len(camps), 1)

    def test_save_compromised_rejects_a_name_with_no_matching_place(self):
        self.db.save_routes([["A", "B"]])
        with self.assertRaises(ValidationError):
            self.db.save_compromised([["ZZZ"]])

    def test_save_compromised_never_mints_a_new_place(self):
        self.db.save_routes([["A", "B"]])
        before = self.db.load_place_registry()
        with self.assertRaises(ValidationError):
            self.db.save_compromised([["ZZZ"]])
        self.assertEqual(self.db.load_place_registry(), before)

    def test_compromised_places_and_routable_graph_work_by_id(self):
        self.db.save_routes([["A", "B", "C"]])
        self.db.save_compromised([["B"]])
        self.assertEqual(self.db.compromised_places(), {self.id("B")})
        self.assertNotIn(self.id("B"), self.db.load_routable_graph())


class MigratePlaceGroupsCommandTests(R2BackedTestCase):
    """The one-time migration: convert routes.json/compromised.json from
    name-string storage to id-based storage, populating places.json — and stay
    a no-op on a re-run."""

    def _run(self, dry_run=False):
        with tempfile.TemporaryDirectory() as tmp, override_settings(DATA_DIR=tmp):
            MigratePlaceGroupsCommand().handle(dry_run=dry_run)

    def _write_raw_routes(self, routes):
        """Pre-migration (string-based) routes.json, written directly —
        bypassing save_routes' own id resolution, which is exactly the state
        the migration itself has to handle."""
        storage.upload_json(self.db.routes_key, routes)

    def test_dry_run_writes_nothing(self):
        self._write_raw_routes([{"places": ["צ. גומא", "מחלף עכו", "אילת"]}])
        self._run(dry_run=True)
        self.assertEqual(self.db.load_place_registry(), {})
        self.assertEqual(
            storage.download_json(self.db.routes_key)[0]["places"],
            ["צ. גומא", "מחלף עכו", "אילת"],
        )

    def test_assigns_distinct_ids_to_the_real_world_collision_case(self):
        # "מ. גולני"/"מחלף גולני" and "צ. צאלים"/"צאלים" each strip to one
        # shared base name — exactly the real data that broke an earlier
        # design keyed by base name alone. No collision here: each of the 4
        # distinct strings gets its own id.
        self._write_raw_routes(
            [{"places": ["מ. גולני", "מחלף גולני", "צ. צאלים", "צאלים"]}]
        )
        self._run()
        self.assertEqual(
            self.db.load_routes()[0]["places"],
            ["מ. גולני", "מחלף גולני", "צ. צאלים", "צאלים"],
        )
        self.assertEqual(len(self.db.load_place_registry()), 4)

    def test_reclassifies_other_places_when_a_new_group_is_recognized(self):
        # Simulate a store migrated *before* some prefix was recognized (e.g. a
        # group added later, as "road"/"כביש" was): an "other" entry whose
        # unstripped name now matches a current PREFIX_PATTERNS entry.
        self._write_raw_routes([{"places": ["כביש 6", "אילת"]}])
        self._run()  # ordinary migration -- "כביש 6" already classifies as road today
        road_id = self.id("כביש 6")

        registry = self.db.load_place_registry()
        registry[road_id] = {"name": "כביש 6", "group": DEFAULT_GROUP}
        storage.upload_json(self.db.places_key, {str(k): v for k, v in registry.items()})

        self._run()  # registry is non-empty now -- the reclassify path

        updated = self.db.load_place_registry()[road_id]
        self.assertEqual(updated, {"name": "6", "group": "road"})
        self.assertEqual(self.db.display_name(updated), "כביש 6")
        # The id itself never changed, so routes.json needed no rewrite.
        self.assertEqual(self.db.load_routes()[0]["places"], ["כביש 6", "אילת"])

    def test_reclassify_is_idempotent(self):
        self._write_raw_routes([{"places": ["כביש 6", "אילת"]}])
        self._run()
        road_id = self.id("כביש 6")
        registry = self.db.load_place_registry()
        registry[road_id] = {"name": "כביש 6", "group": DEFAULT_GROUP}
        storage.upload_json(self.db.places_key, {str(k): v for k, v in registry.items()})

        self._run()
        after_first_reclassify = self.db.load_place_registry()
        self._run()  # nothing left to reclassify
        self.assertEqual(self.db.load_place_registry(), after_first_reclassify)

    def test_migrates_compromised_places_too(self):
        self._write_raw_routes([{"places": ["צ. גומא", "אילת"]}])
        storage.upload_json(self.db.compromised_key, [["צ. גומא"]])
        self._run()
        self.assertEqual(self.db.load_compromised(), [["צ. גומא"]])

    def test_idempotent_on_rerun(self):
        self._write_raw_routes([{"places": ["צ. גומא", "אילת"]}])
        self._run()
        registry, routes = self.db.load_place_registry(), self.db.load_routes()
        self._run()  # already migrated -- must be a no-op
        self.assertEqual(self.db.load_place_registry(), registry)
        self.assertEqual(self.db.load_routes(), routes)


class BranchedRouteExpansionTests(SimpleTestCase):
    """A branched route is a shared tail with converging heads; it flattens to one
    subroute per leaf, identical to authoring each as a separate flat route."""

    # J,T1,T2 is the shared tail (J = מחלף אליפלט, T2 = כביש 6); three heads
    # converge into it — no "primary" head, the tail owns no origin of its own.
    FLAT = [
        ["H1a", "H1b", "J", "T1", "T2"],
        ["H2a", "J", "T1", "T2"],
        ["H3a", "H3b", "J", "T1", "T2"],
    ]
    BRANCHED = [
        {
            "places": ["J", "T1", "T2"],
            "branches": [
                {"places": ["H1a", "H1b"]},
                {"places": ["H2a"]},
                {"places": ["H3a", "H3b"]},
            ],
        }
    ]

    @staticmethod
    def _chains(route):
        """Just the place chains of an expansion (marks asserted separately)."""
        return [subroute["places"] for subroute in expand_route(route)]

    def test_flat_route_expands_to_itself(self):
        self.assertEqual(
            expand_route(["A", "B", "C"]), [{"places": ["A", "B", "C"], "marks": []}]
        )
        self.assertEqual(
            expand_route(
                {"places": ["A", "B", "C"], "marks": [{"from": 0, "to": 1, "priority": 1}]}
            ),
            [{"places": ["A", "B", "C"], "marks": [("A", "B", 1)]}],
        )

    def test_branched_expands_to_the_flat_subroutes(self):
        chains = [r["places"] for r in expand_routes(self.BRANCHED)]
        self.assertEqual(chains, self.FLAT)  # one per leaf, in branch order

    def test_nested_heads_ride_through_their_parent(self):
        # Tail D,E. Head C converges into D and itself splits upstream into A,B and
        # X. Only the two leaves are subroutes — the shared C segment is not.
        route = {
            "places": ["D", "E"],
            "branches": [
                {
                    "places": ["C"],
                    "branches": [{"places": ["A", "B"]}, {"places": ["X"]}],
                },
            ],
        }
        self.assertEqual(
            self._chains(route),
            [["A", "B", "C", "D", "E"], ["X", "C", "D", "E"]],
        )

    def test_tail_may_be_a_single_stop(self):
        # Heads converging straight into the destination — an alternate final approach.
        route = {"places": ["B"], "branches": [{"places": ["A"]}, {"places": ["Q"]}]}
        self.assertEqual(self._chains(route), [["A", "B"], ["Q", "B"]])


class HeadMarkTests(SimpleTestCase):
    """Where a mark sits in the tree decides which corridors it can rate: a head's
    reaches only the leaves below it, the shared tail's reaches every leaf."""

    @staticmethod
    def _marks(route):
        return [subroute["marks"] for subroute in expand_route(route)]

    def test_a_head_mark_applies_to_its_own_subroute_only(self):
        # Two heads into a shared tail; only the second is rated.
        route = {
            "places": ["J", "T"],
            "branches": [
                {"places": ["H1"]},
                {"places": ["H2a", "H2b"], "marks": [{"from": 0, "to": 1, "priority": 2}]},
            ],
        }
        self.assertEqual(self._marks(route), [[], [("H2a", "H2b", 2)]])
        self.assertEqual(
            [s["places"] for s in expand_route(route)],
            [["H1", "J", "T"], ["H2a", "H2b", "J", "T"]],
        )

    def test_a_tail_mark_reaches_every_leaf(self):
        route = {
            "places": ["J", "T1", "T2"],
            "marks": [{"from": 0, "to": 2, "priority": 2}],
            "branches": [{"places": ["H1"]}, {"places": ["H2"]}],
        }
        self.assertEqual(self._marks(route), [[("J", "T2", 2)]] * 2)

    def test_marks_accumulate_down_the_spine(self):
        # Tail D,E (rated 1); head C splits into A,B (rated 3) and X (unrated).
        route = {
            "places": ["D", "E"],
            "marks": [{"from": 0, "to": 1, "priority": 1}],
            "branches": [
                {
                    "places": ["C"],
                    "branches": [
                        {"places": ["A", "B"], "marks": [{"from": 0, "to": 1, "priority": 3}]},
                        {"places": ["X"]},
                    ],
                },
            ],
        }
        # The leaf under A,B carries both its own mark and the tail's; its sibling
        # carries only the tail's.
        self.assertEqual(
            self._marks(route), [[("A", "B", 3), ("D", "E", 1)], [("D", "E", 1)]]
        )

    def test_legacy_head_priorities_upgrade_to_corridor_marks(self):
        # The pre-marks `priority` rated the whole corridor a node generated, so it
        # becomes exactly that: one mark per *leaf*, spanning that leaf's corridor,
        # at the priority the leaf resolved to. H1 inherits the root's 2 and so its
        # whole corridor is rated; H2 overrides with 0 and gains no mark at all —
        # neither head's rating reaches the other, exactly as before.
        route = {
            "places": ["J", "T"],
            "priority": 2,
            "branches": [
                {"places": ["H1a", "H1b"]},
                {"places": ["H2a", "H2b"], "priority": 0},
            ],
        }
        self.assertEqual(
            self._marks(upgrade_node(route)), [[("H1a", "T", 2)], []]
        )

    def test_a_one_stop_head_keeps_its_legacy_rating(self):
        # It has no edge of its own — only the hop into its parent — so a mark over
        # its own places alone could not carry the rating. Over its *corridor* it can,
        # which is what the field always meant.
        route = {
            "places": ["J", "T"],
            "branches": [{"places": ["H"], "priority": 3}],
        }
        self.assertEqual(self._marks(upgrade_node(route)), [[("H", "T", 3)]])

    def test_a_mark_may_run_from_a_head_into_the_shared_tail(self):
        # Frame = the head's own stops followed by everything downstream, so index 2
        # is the tail's first stop. The sibling head is untouched.
        route = {
            "places": ["J", "T"],
            "branches": [
                {"places": ["H1a", "H1b"], "marks": [{"from": 1, "to": 2, "priority": 2}]},
                {"places": ["H2"]},
            ],
        }
        self.assertEqual(self._marks(route), [[("H1b", "J", 2)], []])


class BranchedRouteStorageTests(R2BackedTestCase):
    """Persisting, loading and deriving the graph from branched routes."""

    @staticmethod
    def _named_edges(db, graph):
        """``edge_routes_records`` translated to a set of (endpoint names,
        sorted route indices) — needed because ``flat_db``/``tree_db`` are
        separate ``Database`` instances, each with its *own* place registry, so
        the same place can (and does) mint a different raw id in each; only
        the *names* are meaningfully comparable across them."""
        return {
            (frozenset(db.translate_stops([a, b])), tuple(sorted(route_ids)))
            for a, b, route_ids in graph.edge_routes_records
        }

    @staticmethod
    def _named_marks(db, graph, route_id):
        return tuple(
            (db.translate_stops([a])[0], db.translate_stops([b])[0], p)
            for a, b, p in graph.route_marks(route_id)
        )

    def test_derived_graph_identical_to_flat_authoring(self):
        flat_db = Database(prefix="flat")
        tree_db = Database(prefix="tree")
        flat_db.save_routes(BranchedRouteExpansionTests.FLAT)
        tree_db.save_routes(BranchedRouteExpansionTests.BRANCHED)
        flat_graph, tree_graph = flat_db.load_graph(), tree_db.load_graph()
        # Same edges *and* same per-edge route indices (leaf order matches flat order).
        self.assertEqual(
            self._named_edges(flat_db, flat_graph),
            self._named_edges(tree_db, tree_graph),
        )

    def test_roundtrip_preserves_the_tree(self):
        saved = self.db.save_routes(BranchedRouteExpansionTests.BRANCHED)
        self.assertEqual(saved, self.db.load_routes())
        self.assertEqual(len(saved[0]["branches"]), 3)
        self.assertEqual(saved[0]["branches"][1], {"places": ["H2a"]})

    def test_load_graph_marks_align_across_subroutes(self):
        # A mark on the shared tail rates every corridor that rides it, so all
        # three leaves carry it.
        tail_mark = {"from": 0, "to": 2, "priority": 2}
        self.db.save_routes(
            [{**BranchedRouteExpansionTests.BRANCHED[0], "marks": [tail_mark]}]
        )
        graph = self.db.load_graph()
        self.assertEqual(
            [self._named_marks(self.db, graph, i) for i in (0, 1, 2)],
            [(("J", "T2", 2),)] * 3,
        )

    def test_flat_route_stays_flat_shape(self):
        saved = self.db.save_routes(
            [{"places": ["A", "B", "C"], "marks": [{"from": 0, "to": 1, "priority": 1}]}]
        )
        self.assertEqual(
            saved,
            [{"places": ["A", "B", "C"], "marks": [{"from": 0, "to": 1, "priority": 1}]}],
        )
        self.assertNotIn("branches", saved[0])

    def test_branched_tail_may_be_one_stop(self):
        saved = self.db.save_routes(
            [{"places": ["B"], "branches": [{"places": ["A"]}, {"places": ["Q"]}]}]
        )
        self.assertEqual(len(saved[0]["branches"]), 2)

    def test_rejects_branchless_single_stop_route(self):
        with self.assertRaises(ValidationError):
            self.db.save_routes([{"places": ["A"]}])

    def test_rejects_empty_tail(self):
        with self.assertRaises(ValidationError):
            self.db.save_routes(
                [{"places": [], "branches": [{"places": ["A"]}, {"places": ["Q"]}]}]
            )

    def test_rejects_empty_branch(self):
        with self.assertRaises(ValidationError):
            self.db.save_routes([{"places": ["A", "B"], "branches": [{"places": []}]}])

    def test_rejects_a_repeated_stop_in_one_chain(self):
        # The graph keys its nodes by place, so the two "B"s are one node and the
        # stretch between them is a loop the router may cut — a corridor that
        # silently loses its middle while still reading as one authored route.
        with self.assertRaises(ValidationError):
            self.db.save_routes([{"places": ["A", "B", "C", "B", "D"]}])

    def test_rejects_a_head_stop_repeated_in_the_shared_tail(self):
        # The leaf chain concatenates head and tail, so the repeat is just as fatal
        # across the junction as inside one node.
        with self.assertRaises(ValidationError):
            self.db.save_routes(
                [{"places": ["J", "T"], "branches": [{"places": ["H", "T"]}]}]
            )

    def test_allows_the_same_stop_on_two_sibling_heads(self):
        # Nothing rides two sibling heads, so neither corridor visits "P" twice.
        saved = self.db.save_routes(
            [{"places": ["J", "T"], "branches": [{"places": ["P", "A"]}, {"places": ["P", "B"]}]}]
        )
        self.assertEqual(len(saved[0]["branches"]), 2)

    def test_a_repeated_stop_never_reaches_the_graph(self):
        # The regression this rule exists for: a route naming one interchange twice
        # let the router jump straight from the first occurrence to what followed
        # the second, skipping every stop between them at a perfect concentration
        # score. Refusing the save is what keeps that edge out of the graph.
        self.db.save_routes([{"places": ["A", "B", "C", "D", "E"]}])
        with self.assertRaises(ValidationError):
            self.db.save_routes([{"places": ["A", "B", "C", "D", "B", "E"]}])
        graph = self.db.load_graph()
        self.assertNotIn(self.id("E"), graph.neighbors(self.id("B")))

    def test_roundtrip_preserves_a_head_mark(self):
        head_mark = {"from": 0, "to": 1, "priority": 2}
        saved = self.db.save_routes(
            [
                {
                    "places": ["J", "T"],
                    "branches": [
                        {"places": ["H1a", "H1b"]},
                        {"places": ["H2a", "H2b"], "marks": [head_mark]},
                    ],
                }
            ]
        )
        self.assertEqual(saved, self.db.load_routes())
        # Stated on the head that has one, absent on the head that has none.
        self.assertEqual(
            saved[0]["branches"],
            [
                {"places": ["H1a", "H1b"]},
                {"places": ["H2a", "H2b"], "marks": [head_mark]},
            ],
        )

    def test_load_graph_rates_each_head_separately(self):
        self.db.save_routes(
            [
                {
                    "places": ["J", "T"],
                    "branches": [
                        {"places": ["H1a", "H1b"]},
                        {
                            "places": ["H2a", "H2b"],
                            "marks": [{"from": 0, "to": 1, "priority": 3}],
                        },
                    ],
                }
            ]
        )
        graph = self.db.load_graph()
        # Leaf 0 (H1) is unmarked; leaf 1 (H2) carries its head's mark.
        self.assertEqual(graph.route_marks(0), ())
        self.assertEqual(self._named_marks(self.db, graph, 1), (("H2a", "H2b", 3),))
        # The shared tail is outside the mark, so it stays free for both — a head's
        # downgrade doesn't spoil the road for its sibling.
        self.assertEqual(graph.edge_priority(self.id("J"), self.id("T")), 0)

    def test_rejects_out_of_range_head_priority(self):
        with self.assertRaises(ValidationError):
            self.db.save_routes(
                [{"places": ["T"], "branches": [{"places": ["A"], "priority": 9}]}]
            )

    def test_rejects_non_int_head_priority(self):
        with self.assertRaises(ValidationError):
            self.db.save_routes(
                [{"places": ["T"], "branches": [{"places": ["A"], "priority": True}]}]
            )

    def test_a_head_mark_may_reach_into_the_shared_tail(self):
        # The head's frame is its own stops followed by everything downstream, so a
        # mark can span the junction — a road doesn't care where the tree was split.
        saved = self.db.save_routes(
            [
                {
                    "places": ["J", "T"],
                    "branches": [
                        {"places": ["H1"], "marks": [{"from": 0, "to": 2, "priority": 2}]},
                        {"places": ["H2"]},
                    ],
                }
            ]
        )
        self.assertEqual(
            saved[0]["branches"][0]["marks"], [{"from": 0, "to": 2, "priority": 2}]
        )
        graph = self.db.load_graph()
        # It rates the corridor below that head, from the head to the tail stop it
        # reaches — and leaves the sibling's corridor alone.
        self.assertEqual(self._named_marks(self.db, graph, 0), (("H1", "T", 2),))
        self.assertEqual(graph.route_marks(1), ())

    def test_rejects_a_head_mark_past_the_destination(self):
        # One stop past the tail's last: the frame ends at the destination.
        with self.assertRaises(ValidationError):
            self.db.save_routes(
                [
                    {
                        "places": ["J", "T"],
                        "branches": [
                            {"places": ["H1"], "marks": [{"from": 0, "to": 3, "priority": 2}]}
                        ],
                    }
                ]
            )

    def test_rejects_a_mark_starting_downstream_of_the_node_that_stores_it(self):
        # `from` must sit in the node's own places: a stretch that starts in the tail
        # is the tail's to state, and storing it on a head would let one stretch be
        # written two ways (and rated twice).
        with self.assertRaises(ValidationError):
            self.db.save_routes(
                [
                    {
                        "places": ["J", "T"],
                        "branches": [
                            {"places": ["H1"], "marks": [{"from": 1, "to": 2, "priority": 2}]}
                        ],
                    }
                ]
            )

    def test_head_mark_matches_authoring_the_subroutes_flat(self):
        """The whole point: a marked head is exactly the equivalent flat route."""
        flat_db = Database(prefix="flat")
        tree_db = Database(prefix="tree")
        flat_db.save_routes(
            [
                {"places": ["H1a", "H1b", "J", "T"]},
                {
                    "places": ["H2a", "H2b", "J", "T"],
                    "marks": [{"from": 0, "to": 1, "priority": 3}],
                },
            ]
        )
        tree_db.save_routes(
            [
                {
                    "places": ["J", "T"],
                    "branches": [
                        {"places": ["H1a", "H1b"]},
                        {
                            "places": ["H2a", "H2b"],
                            "marks": [{"from": 0, "to": 1, "priority": 3}],
                        },
                    ],
                }
            ]
        )
        flat_graph, tree_graph = flat_db.load_graph(), tree_db.load_graph()
        self.assertEqual(
            self._named_edges(flat_db, flat_graph), self._named_edges(tree_db, tree_graph)
        )
        self.assertEqual(
            [self._named_marks(flat_db, flat_graph, i) for i in (0, 1)],
            [self._named_marks(tree_db, tree_graph, i) for i in (0, 1)],
        )

    def test_pathfinding_matches_flat_authoring(self):
        flat_db = Database(prefix="flat")
        tree_db = Database(prefix="tree")
        flat_db.save_routes(BranchedRouteExpansionTests.FLAT)
        tree_db.save_routes(BranchedRouteExpansionTests.BRANCHED)
        flat_finder = RouteFinder(flat_db.load_graph())
        tree_finder = RouteFinder(tree_db.load_graph())
        flat_ranked, _ = flat_finder.rank_candidates(flat_db.place_id("H2a"), flat_db.place_id("T2"))
        tree_ranked, _ = tree_finder.rank_candidates(tree_db.place_id("H2a"), tree_db.place_id("T2"))
        flat_top = [flat_db.translate_stops(r.stops) for r in flat_finder.select_diverse(flat_ranked, k=None)]
        tree_top = [tree_db.translate_stops(r.stops) for r in tree_finder.select_diverse(tree_ranked, k=None)]
        self.assertEqual(flat_top, tree_top)
        self.assertEqual(flat_top[0], ["H2a", "J", "T1", "T2"])


class DerivedGraphFreshnessTests(R2BackedTestCase):
    """The derived graph must never outlive the routes it was derived from.

    ``edge_routes.json`` is only rebuilt on save, so anything that changes
    ``routes.json`` behind the store's back — or changes the derivation itself —
    used to leave the router riding edges no route asserts, silently and forever.
    Every load now checks a fingerprint and rebuilds on any mismatch.
    """

    # A converging tree: two heads that meet only at the shared tail. The heads'
    # last stops (H1b, H2b) must NEVER be adjacent to each other — welding them is
    # exactly what a stale derived object looked like in the wild.
    TREE = [
        {
            "places": ["T1", "T2"],
            "branches": [{"places": ["H1a", "H1b"]}, {"places": ["H2a", "H2b"]}],
        }
    ]

    def edges(self):
        registry = self.db.load_place_registry()
        return {
            frozenset(self.db.translate_stops([a, b], registry))
            for a, b, _ in storage.download_json(self.db.edge_routes_key)
        }

    def write_routes_out_of_band(self, routes):
        """Change routes.json without going through save_routes (no rebuild)."""
        storage.upload_json(self.db.routes_key, routes)

    def test_heads_of_a_tree_are_not_welded_together(self):
        self.db.save_routes(self.TREE)
        self.assertNotIn(frozenset(("H1b", "H2b")), self.edges())
        self.assertIn(frozenset(("H1b", "T1")), self.edges())
        self.assertIn(frozenset(("H2b", "T1")), self.edges())

    def test_out_of_band_route_change_rebuilds_on_load(self):
        self.db.save_routes(self.TREE)
        # Written directly to routes.json (bypassing save_routes' own id
        # resolution), so it must already be id-based, like a real out-of-band
        # restore of this store's own data would be. "H2c" is a genuinely new
        # stop, registered directly (see `register`) since this bypasses the
        # normal save path that would otherwise mint it.
        h2c = self.register("H2c")
        extended = [
            {
                "places": [self.id("T1"), self.id("T2")],
                "branches": [
                    {"places": [self.id("H1a"), self.id("H1b")]},
                    {"places": [self.id("H2a"), self.id("H2b"), h2c]},
                ],
            }
        ]
        self.write_routes_out_of_band(extended)
        graph = self.db.load_graph()
        self.assertIn(frozenset(("H2b", "H2c")), self.edges())
        self.assertIn(h2c, graph.places())

    def test_restoring_a_mismatched_backup_rebuilds(self):
        # Restoring an *older* derived object (+ its fingerprint) over current
        # routes — copying a data/ backup over a live store. The fingerprint
        # travels with the edges it describes, so the mismatch against the routes
        # actually present is what catches it.
        self.db.save_routes([{"places": ["OLD1", "OLD2"], "priority": 0}])
        old_edges = storage.download_json(self.db.edge_routes_key)
        old_fingerprint = storage.download_json(self.db.fingerprint_key)

        self.db.save_routes(self.TREE)
        storage.upload_json(self.db.edge_routes_key, old_edges)
        storage.upload_json(self.db.fingerprint_key, old_fingerprint)

        self.db.load_graph()
        self.assertNotIn(frozenset(("OLD1", "OLD2")), self.edges())
        self.assertIn(frozenset(("H1b", "T1")), self.edges())

    def test_tampered_derived_object_alone_is_not_detected(self):
        # The boundary of the guard, pinned deliberately: the fingerprint answers
        # "which routes were these derived from", not "has this file been edited".
        # Hand-editing edge_routes.json while routes.json stays put is therefore
        # invisible — catching it would mean downloading and digesting the edges on
        # every load, including loads that never read them.
        self.db.save_routes(self.TREE)
        records = storage.download_json(self.db.edge_routes_key)
        storage.upload_json(
            self.db.edge_routes_key, records + [[self.id("H1b"), self.id("H2b"), [0]]]
        )
        self.db.load_graph()
        self.assertIn(frozenset(("H1b", "H2b")), self.edges())

    def test_derivation_version_bump_rebuilds(self):
        self.db.save_routes(self.TREE)
        storage.upload_json(self.db.edge_routes_key, [["bogus", "edge", [0]]])
        with mock.patch.object(db_module, "DERIVATION_VERSION", db_module.DERIVATION_VERSION + 1):
            self.db.load_graph()
        self.assertNotIn(frozenset(("bogus", "edge")), self.edges())

    def test_missing_fingerprint_rebuilds(self):
        # A store seeded (or written) before fingerprints existed has none.
        self.db.save_routes(self.TREE)
        storage.upload_json(self.db.edge_routes_key, [["bogus", "edge", [0]]])
        boto3.client("s3", region_name="us-east-1").delete_object(
            Bucket=_R2_TEST_ENV["R2_BUCKET_NAME"], Key=self.db.fingerprint_key
        )
        self.db.load_graph()
        self.assertNotIn(frozenset(("bogus", "edge")), self.edges())

    def test_fresh_store_does_not_rebuild(self):
        # The check must be cheap in the common case: a matching fingerprint means
        # no recomputation at all, however many times the store is read.
        self.db.save_routes(self.TREE)
        with mock.patch.object(
            Database, "_rebuild_graph", autospec=True
        ) as rebuild:
            self.db.load_graph()
            self.db.load_routes()
            self.db.load_expanded_routes()
        rebuild.assert_not_called()
