import { http, unwrap } from "./httpClient.js";

export function registerUser(payload) {
  return unwrap(http.post("/accounts/register/", payload));
}

export function loginUser(personalId, password) {
  return unwrap(http.post("/accounts/login/", { personal_id: personalId, password }));
}

export function refreshAccessToken(refresh) {
  return unwrap(http.post("/accounts/token/refresh/", { refresh }));
}

export function logoutUser(refresh) {
  return unwrap(http.post("/accounts/logout/", { refresh }));
}

export function fetchMe() {
  return unwrap(http.get("/accounts/me/"));
}

export function fetchAllUsers() {
  return unwrap(http.get("/accounts/users/"));
}

export function promoteUser(personalId) {
  return unwrap(http.post(`/accounts/users/${personalId}/promote/`));
}

export function demoteUser(personalId) {
  return unwrap(http.post(`/accounts/users/${personalId}/demote/`));
}
