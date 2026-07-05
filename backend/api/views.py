"""DRF function views for the traffic-arteries API.

Function views with @api_view + rest_framework.response.Response, per spec.
"""

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import db, graph
from .db import ValidationError


@api_view(["GET"])
def places(request):
    """All known place names, sorted — feeds the autocomplete inputs."""
    adjacency = db.load_graph()
    return Response(graph.all_places(adjacency))


@api_view(["GET", "PUT"])
def routes(request):
    """GET the full routes list, or PUT a replacement list.

    A successful PUT re-validates the payload and regenerates graph.json.
    """
    if request.method == "GET":
        return Response(db.load_routes())

    try:
        saved = db.save_routes(request.data)
    except ValidationError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(saved)


@api_view(["GET"])
def network(request):
    """Graph as {nodes, links} for react-force-graph-2d (read-only view)."""
    adjacency = db.load_graph()
    return Response(graph.to_network(adjacency))


@api_view(["POST"])
def path(request):
    """Top 3 shortest paths between two points.

    Body: ``{"start": <place>, "end": <place>}``.
    Response: ``{"paths": [[...], ...]}`` — an empty list means no route exists.
    """
    start = (request.data.get("start") or "").strip()
    end = (request.data.get("end") or "").strip()

    if not start or not end:
        return Response(
            {"detail": "יש לבחור נקודת מוצא ונקודת יעד."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    adjacency = db.load_graph()
    paths = graph.k_shortest_paths(adjacency, start, end, k=3)
    return Response({"paths": paths})
