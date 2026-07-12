import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchAllUsers, promoteUser, demoteUser } from "../../api/accounts.js";

export function useUserManagement() {
  const [users, setUsers] = useState([]);
  const [query, setQuery] = useState("");
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

  const filteredUsers = useMemo(() => {
    const q = query.trim();
    if (!q) return users;
    return users.filter((u) => u.personal_id.includes(q));
  }, [users, query]);

  return { users: filteredUsers, query, setQuery, loading, error, promote, demote, reload };
}
