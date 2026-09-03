"""DRF function views for the traffic-arteries API.

Function views with @api_view + rest_framework.response.Response, per spec.
"""

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from accounts.permissions import IsEditorOrAdmin

from .db import ValidationError, database
from .graph import RouteFinder
from .path_meta import route_meta

# Product decision: a search shows the three best routes. Named rather than a
# bare ``[:3]`` literal so the count lives in one place and never gets encoded as
# a magic ``k`` — routing is asked for the full ranked pool (the ``k=None``
# sentinel) and this is the only thing that truncates it.
TOP_N = 3


@api_view(["GET"])
def health(request):
    """Liveness probe for the frontend's startup gate.

    Deliberately touches neither the R2 store nor the database — it answers as
    soon as the process is up. The frontend polls this before rendering, so it
    can wait out Render's free-tier cold start (a spun-down service takes tens
    of seconds to wake) behind a single loader, instead of every page racing an
    unfinished request and, e.g., reporting valid places as unknown.
    """
    return Response({"status": "ok"})


@api_view(["GET"])
def places(request):
    """Known, currently-routable place names, sorted — feeds the path-finding
    autocomplete inputs. Compromised (temporarily unavailable) destinations are
    excluded, since they can't be planned through."""
    graph = database.load_routable_graph()
    return Response(sorted(database.translate_stops(graph.places())))


@api_view(["GET", "PUT"])
@permission_classes([IsEditorOrAdmin])
def routes(request):
    """GET the full routes list, or PUT a replacement list.

    A successful PUT re-validates the payload and regenerates the derived graph.
    """
    if request.method == "GET":
        return Response(database.load_routes())

    try:
        saved = database.save_routes(request.data)
    except ValidationError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(saved)


@api_view(["GET", "PUT"])
@permission_classes([IsEditorOrAdmin])
def compromised(request):
    """GET the compromised-destination groups, or PUT a replacement list.

    Each group is a list of destination names temporarily marked unavailable
    together. A successful PUT re-validates every destination against the
    closed list of known places.
    """
    if request.method == "GET":
        return Response(database.load_compromised())

    try:
        saved = database.save_compromised(request.data)
    except ValidationError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(saved)


@api_view(["GET"])
@permission_classes([IsEditorOrAdmin])
def network(request):
    """Graph as {nodes, links} for react-force-graph-2d (read-only view).

    The full network, including compromised destinations — each node is
    annotated ``compromised`` so the frontend can flag them, rather than
    hiding them the way routing/place-picking does.
    """
    graph = database.load_graph()
    payload = graph.to_network()
    compromised_places = database.compromised_places()
    registry = database.load_place_registry()

    for node in payload["nodes"]:
        entry = registry[node["id"]]
        node["compromised"] = node["id"] in compromised_places
        node["group"] = entry["group"]
        node["id"] = database.display_name(entry)
    for link in payload["links"]:
        link["source"] = database.display_name(registry[link["source"]])
        link["target"] = database.display_name(registry[link["target"]])
    return Response(payload)


@api_view(["POST"])
def path(request):
    """Top 3 routes between two points, optionally via required stops.

    "Best" is the route that rides one *good* authored route as far as possible:
    the best priority tier first, then the highest concentration score. A route's
    tier is the worst *priority mark* its ridden sub-routes complete — a mark rates
    a stretch of an authored route, and only a ride covering that stretch whole pays
    for it.

    Body: ``{"start": <place>, "end": <place>, "via": [<place>, ...]}``.
    ``via`` is optional — required intermediate stops the route must pass
    through (visited in an optimised order).
    Response: ``{"paths": [[...], ...], "meta": [{"routeCount", "match",
    "priority", "routes", "legs"}, ...], "compromisedDetour": [...]}`` — ``paths`` are
    the stop chains; ``meta[i]`` gives the match percentage (the *ranking* score
    ``Route.q`` — priority-free concentration tempered by the crossroad-distance
    term, so the number shown always agrees with the order the results are listed in
    and does not move when an artery is re-prioritised), the
    route's ``priority`` *tier* (the worst priority among the sub-routes it rides,
    each being the worst mark that sub-route completes, i.e. the max over
    ``routes[].priority`` below — why a longer route may outrank a shorter one, so
    the UI must surface it), and which authored routes route ``i``
    merges (labelled by their
    endpoints, each with its own ``priority`` and a ``startIndex``/``endIndex``
    pair — inclusive, 0-based indices into ``paths[i]`` — for the stop range it
    covers).

    ``meta[i]["legs"]`` is how the trip divides at the required stops — one entry per
    stretch between consecutive stops, each with its own ``startIndex``/``endIndex``
    into ``paths[i]``, endpoint names, ``match``, ``priority`` and its slice of
    ``routes``. It is **always present and never empty**: with no ``via`` it holds a
    single leg spanning the whole chain, so the UI has one shape to render. Note that
    with required stops ``paths[i]`` may repeat a place name — a stop hanging off a
    junction is left by driving back out through it — so chain items must be keyed by
    index, not by name.

    ``compromisedDetour`` lists compromised destinations that the natural
    (unfiltered) top-3 routes would have used, had they not been temporarily
    unavailable — empty unless ``paths`` is non-empty and a detour actually
    happened. Empty ``paths`` means no route.
    """
    start = (request.data.get("start") or "").strip()
    end = (request.data.get("end") or "").strip()

    via_raw = request.data.get("via")
    via = [str(v).strip() for v in via_raw if str(v).strip()] if isinstance(via_raw, list) else []

    if not start or not end:
        return Response(
            {"detail": "יש לבחור נקודת מוצא ונקודת יעד."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Request bodies are display-name strings, per the API contract — resolve
    # to the internal ids the (now id-keyed) graph actually uses. An
    # unresolvable name means "no such place," same as an unknown place always
    # meant here: no route, not an error.
    registry = database.load_place_registry()
    start_id, end_id, *via_ids = database.resolve_places([start, end, *via])
    if start_id is None or end_id is None or any(v is None for v in via_ids):
        return Response({"paths": [], "meta": [], "compromisedDetour": []})

    compromised = database.compromised_places()
    graph = database.load_graph()
    # Expanded subroutes (one per tree node) — this is the list the graph's route
    # indices line up with, so `run.route_id` labels resolve correctly for branched
    # routes too. Still id-based (places() gives ids), like the graph itself.
    routes = database.load_expanded_routes()

    # Rank the candidate pool once (the single sort), then select over it twice:
    # the natural best (to report what the compromise costs) and the best that
    # avoids compromised destinations (what we actually show). No re-sort, and the
    # compromised-free results are *selected* — arena and diversity budget computed
    # among showable routes — not a natural list with holes filtered out of it.
    finder = RouteFinder(graph)
    ranked, stretch = finder.rank_candidates(start_id, end_id, via=via_ids)
    natural = finder.select_diverse(ranked, k=None, max_stretch=stretch)
    detour_ids = (
        sorted({stop for r in natural[:TOP_N] for stop in r.stops} & compromised)
        if compromised
        else []
    )
    clean = (
        finder.select_diverse(ranked, k=None, max_stretch=stretch, exclude=compromised)
        if compromised
        else natural
    )
    top = clean[:TOP_N]
    paths = [database.translate_stops(r.stops, registry) for r in top]
    meta = [route_meta(r, registry, routes) for r in top]
    detour = sorted(database.translate_stops(detour_ids, registry)) if paths else []
    return Response({"paths": paths, "meta": meta, "compromisedDetour": detour})
