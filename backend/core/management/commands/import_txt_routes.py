import json
from django.core.management.base import BaseCommand
from api.db import _rebuild_graph
from functools import lru_cache


POLYGONS = ['רמה"ג']

class Command(BaseCommand):
    help = ""

    @staticmethod
    def fill_missing_destinations(routes):
        
        best_known_path = {}

        def index_subpaths(route):
            n = len(route)
            for i in range(n):
                for j in range(i + 1, n):
                    start, end = route[i], route[j]
                    subpath = route[i:j+1]
                    displacement = (start, end)
                    if displacement not in best_known_path or len(subpath) > len(best_known_path[displacement]):
                        best_known_path[displacement] = subpath

        for route in routes:
            index_subpaths(route)
            index_subpaths(list(reversed(route)))

        # @lru_cache(maxsize=None)
        def expand_gap(u, v, seen_places=None):
            displacement = (u, v)
            if u == v or displacement not in best_known_path:
                return list(displacement)
            
            path = best_known_path[displacement]
            # return path
            # print(f"{path}\n{(u, v)}\n{seen_places}\n-----------")
            if len(path) == 2:
                return path
            
            if seen_places is None:
                seen_places = frozenset([u, v])
            else:
                seen_places = seen_places | frozenset([u, v])
            
            expanded_path = [path[0]]
            for i in range(len(path) - 1):
                if path[i+1] in seen_places:
                    continue

                sub_expended = expand_gap(path[i], path[i+1], seen_places)
                expanded_path.extend(sub_expended[1:])

            return expanded_path

        filled_routes = []
        for route in routes:
            assert len(route) >= 2
            
            filled_route = [route[0]]
            for i in range(len(route) - 1):
                u, v = route[i], route[i+1]
                if v not in filled_route:
                    expanded = expand_gap(u, v, frozenset(filled_route[:i]))
                    filled_route.extend(expanded[1:])
            
            filled_routes.append(filled_route)
        
        return filled_routes

    def handle(self, *args, **options):
        with open("./core/data/routes.txt", "r", encoding="utf-8") as f:
            routes = []

            for line in f:
                # print(line.strip().split(": "))
                displacement, route = line.strip().split(": ")
                displacement = displacement.split(" - ")
                route = route.split(", ")
                
                if displacement[0] != route[0] and not (displacement[0] in POLYGONS):
                    route.insert(0, displacement[0])

                if displacement[1] != route[-1] and not (displacement[1] in POLYGONS):
                    route.append(displacement[1])
                
                routes.append(route)

        # add the camp label if missing
        places = set(place for route in routes for place in route)

        for i, route in enumerate(routes):
            for j, place in enumerate(route):
                if (camp_label := f"מ. {place}") in places:
                    routes[i][j] = camp_label

        # insert skiped destinations
        routes = self.fill_missing_destinations(routes)

        # save the routes in db
        with open("data/routes.json", "w", encoding="utf-8") as f:
            json.dump(routes, f, ensure_ascii=False, indent=2)
        
        _rebuild_graph(routes)
