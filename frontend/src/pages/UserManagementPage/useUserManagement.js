import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchAllUsers, promoteUser, demoteUser } from "../../api/accounts.js";

const ROLE_ORDER = { user: 0, editor: 1, admin: 2 };

function sortValue(user, key) {
  if (key === "name") return `${user.first_name} ${user.last_name}`.trim();
  if (key === "role") return ROLE_ORDER[user.role] ?? 0;
  return user.personal_id;
}

export function useUserManagement() {
  const [users, setUsers] = useState([]);
  const [query, setQuery] = useState("");
  const [roleFilter, setRoleFilter] = useState("all");
  const [sort, setSort] = useState({ key: "personal_id", dir: "asc" });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const reload = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setUsers(await fetchAllUsers());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  async function promote(personalId) {
    setError("");
    try {
      await promoteUser(personalId);
      await reload();
    } catch (e) {
      setError(e.message);
    }
  }

  async function demote(personalId) {
    setError("");
    try {
      await demoteUser(personalId);
      await reload();
    } catch (e) {
      setError(e.message);
    }
  }

  function toggleSort(key) {
    setSort((s) => (s.key === key ? { key, dir: s.dir === "asc" ? "desc" : "asc" } : { key, dir: "asc" }));
  }

  const filteredUsers = useMemo(() => {
    const q = query.trim();
    let result = users;

    if (q) {
      result = result.filter(
        (u) => u.personal_id.includes(q) || `${u.first_name} ${u.last_name}`.includes(q),
      );
    }

    if (roleFilter !== "all") {
      result = result.filter((u) => u.role === roleFilter);
    }

    return [...result].sort((a, b) => {
      const av = sortValue(a, sort.key);
      const bv = sortValue(b, sort.key);
      const cmp = av < bv ? -1 : av > bv ? 1 : 0;
      return sort.dir === "asc" ? cmp : -cmp;
    });
  }, [users, query, roleFilter, sort]);

  return {
    users: filteredUsers,
    allUsers: users,
    query,
    setQuery,
    roleFilter,
    setRoleFilter,
    sort,
    toggleSort,
    loading,
    error,
    promote,
    demote,
    reload,
  };
}
