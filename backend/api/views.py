"""DRF function views for the traffic-arteries API.

Function views with @api_view + rest_framework.response.Response, per spec.
"""

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .db import ValidationError, database
from .graph import RouteFinder


@api_view(["GET"])
def places(request):
    """All known place names, sorted — feeds the autocomplete inputs."""
    graph = database.load_graph()
    return Response(graph.places())


@api_view(["GET", "PUT"])
def routes(request):
    """GET the full routes list, or PUT a replacement list.

    A successful PUT re-validates the payload and regenerates graph.json.
    """
    if request.method == "GET":
        return Response(database.load_routes())

    try:
        saved = database.save_routes(request.data)
    except ValidationError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(saved)


@api_view(["GET"])
def network(request):
    """Graph as {nodes, links} for react-force-graph-2d (read-only view)."""
    graph = database.load_graph()
    return Response(graph.to_network())


@api_view(["POST"])
def path(request):
    """Top 3 routes between two points, optionally via required stops.

    "Best" is the route that merges the fewest authored routes, tiebroken by
    fewest intersections.

    Body: ``{"start": <place>, "end": <place>, "via": [<place>, ...]}``.
    ``via`` is optional — required intermediate stops the route must pass
    through (visited in an optimised order).
    Response: ``{"paths": [[...], ...], "meta": [{"routeCount", "routes"}, ...]}``
    — ``paths`` are the stop chains; ``meta[i]`` describes which authored routes
    route ``i`` merges (labelled by their endpoints). Empty lists mean no route.
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

    graph = database.load_graph()
    routes = database.load_routes()  # originals, for human-readable labels

    def label(index):
        route = routes[index] if 0 <= index < len(routes) else None
        if route:
            return f"{route[0]} - {route[-1]}"
        return f"ציר {index + 1}"

    results = RouteFinder(graph).find_routes(start, end, k=3, via=via)
    paths = [r.stops for r in results]
    meta = [
        {
            "routeCount": r.route_count,
            "routes": [{"id": i, "label": label(i)} for i in r.route_ids],
        }
        for r in results
    ]
    return Response({"paths": paths, "meta": meta})
