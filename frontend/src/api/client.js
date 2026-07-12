// Thin fetch wrappers around the Django API. All requests go through the Vite
// dev proxy at /api, so no base URL or CORS handling is required.

async function request(url, options = {}) {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const message = (data && data.detail) || "אירעה שגיאה בשרת.";
    throw new Error(message);
  }
  return data;
}

export function getPlaces() {
  return request("/api/places/");
}

export function getRoutes() {
  return request("/api/routes/");
}

export function saveRoutes(routes) {
  return request("/api/routes/", {
    method: "PUT",
    body: JSON.stringify(routes),
  });
}

export function getCompromised() {
  return request("/api/compromised/");
}

export function saveCompromised(groups) {
  return request("/api/compromised/", {
    method: "PUT",
    body: JSON.stringify(groups),
  });
}

export function getGraph() {
  return request("/api/graph/");
}

export function findPaths(start, end, via = []) {
  return request("/api/path/", {
    method: "POST",
    body: JSON.stringify({ start, end, via }),
  });
}
