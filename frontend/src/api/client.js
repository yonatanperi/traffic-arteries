// Thin axios wrappers around the Django API. All requests go through the
// Vite dev proxy at /api, so no base URL or CORS handling is required.
// The shared axios instance transparently attaches the auth header and
// retries on token refresh — see httpClient.js.

import { http, unwrap } from "./httpClient.js";

export function getPlaces() {
  return unwrap(http.get("/places/"));
}

export function getRoutes() {
  return unwrap(http.get("/routes/"));
}

export function saveRoutes(routes) {
  return unwrap(http.put("/routes/", routes));
}

export function getCompromised() {
  return unwrap(http.get("/compromised/"));
}

export function saveCompromised(groups) {
  return unwrap(http.put("/compromised/", groups));
}

export function getGraph() {
  return unwrap(http.get("/graph/"));
}

export function findPaths(start, end, via = []) {
  return unwrap(http.post("/path/", { start, end, via }));
}
