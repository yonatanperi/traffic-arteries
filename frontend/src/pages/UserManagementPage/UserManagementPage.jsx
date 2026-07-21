import PageHeader from "../../components/ui/PageHeader";
import Page from "../../components/layout/Page";
import Pill from "../../components/ui/Pill";
import Button from "../../components/ui/Button";
import LoaderLayout from "../../components/ui/LoaderLayout/LoaderLayout.jsx";
import EmptyState from "../../components/ui/EmptyState";
import { IconChevron, IconSearch } from "../../components/ui/icons";
import { useUserManagement } from "./useUserManagement.js";
import "./UserManagementPage.css";

const ROLE_LABELS = { user: "משתמש", editor: "עורך", admin: "מנהל" };
const ROLE_TONES = { user: "default", editor: "accent", admin: "accent" };
const ROLE_FILTERS = [
  { value: "all", label: "הכל" },
  { value: "user", label: ROLE_LABELS.user },
  { value: "editor", label: ROLE_LABELS.editor },
  { value: "admin", label: ROLE_LABELS.admin },
];
const COLUMNS = [
  { key: "personal_id", label: "מספר אישי" },
  { key: "name", label: "שם" },
  { key: "role", label: "הרשאה" },
];

export default function UserManagementPage() {
  const {
    users,
    allUsers,
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
  } = useUserManagement();

  const total = allUsers.length;
  const editorCount = allUsers.filter((u) => u.role === "editor").length;
  const adminCount = allUsers.filter((u) => u.role === "admin").length;

  return (
    <Page>
      <PageHeader
        title="ניהול משתמשים"
        subtitle="הענקת הרשאות עורך ומעקב אחר משתמשי המערכת."
      />

      <div className="user-mgmt-stats">
        <div className="user-mgmt-stat card">
          <span className="user-mgmt-stat-value">{total}</span>
          <span className="user-mgmt-stat-label">סה״כ משתמשים</span>
        </div>
        <div className="user-mgmt-stat card">
          <span className="user-mgmt-stat-value">{editorCount}</span>
          <span className="user-mgmt-stat-label">עורכים</span>
        </div>
        <div className="user-mgmt-stat card">
          <span className="user-mgmt-stat-value">{adminCount}</span>
          <span className="user-mgmt-stat-label">מנהלים</span>
        </div>
      </div>

      <div className="user-mgmt-toolbar">
        <div className="user-mgmt-search-wrap">
          <IconSearch size={16} className="user-mgmt-search-icon" />
          <input
            className="user-mgmt-search"
            type="text"
            placeholder="חיפוש לפי מספר אישי או שם…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>

        <div className="user-mgmt-filters">
          {ROLE_FILTERS.map((f) => (
            <Pill
              key={f.value}
              as="button"
              size="sm"
              className={
                "user-mgmt-filter-pill" + (roleFilter === f.value ? " user-mgmt-filter-pill--on" : "")
              }
              onClick={() => setRoleFilter(f.value)}
              aria-pressed={roleFilter === f.value}
            >
              {f.label}
            </Pill>
          ))}
        </div>
      </div>

      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}

      {loading ? (
        <LoaderLayout label="טוען משתמשים…" />
      ) : users.length === 0 ? (
        <EmptyState title="לא נמצאו משתמשים" />
      ) : (
        <div className="user-mgmt-table card">
          <div className="user-mgmt-row user-mgmt-row--head">
            {COLUMNS.map((col) => (
              <button
                key={col.key}
                type="button"
                className="user-mgmt-sort-btn"
                aria-sort={sort.key === col.key ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}
                onClick={() => toggleSort(col.key)}
              >
                {col.label}
                <IconChevron
                  size={12}
                  className={
                    "user-mgmt-sort-icon" +
                    (sort.key === col.key ? " user-mgmt-sort-icon--active" : "") +
                    (sort.key === col.key && sort.dir === "desc" ? " user-mgmt-sort-icon--desc" : "")
                  }
                />
              </button>
            ))}
            <span />
          </div>
          {users.map((u) => (
            <div className="user-mgmt-row" key={u.personal_id}>
              <span>{u.personal_id}</span>
              <span>
                {u.first_name} {u.last_name}
              </span>
              <span>
                <Pill tone={ROLE_TONES[u.role]}>{ROLE_LABELS[u.role]}</Pill>
              </span>
              <span className="user-mgmt-actions">
                {u.role === "user" && (
                  <Button
                    size="sm"
                    variant="primary"
                    onClick={() => promote(u.personal_id)}
                  >
                    הפוך לעורך
                  </Button>
                )}
                {u.role === "editor" && (
                  <Button
                    size="sm"
                    variant="danger"
                    onClick={() => demote(u.personal_id)}
                  >
                    בטל הרשאת עורך
                  </Button>
                )}
              </span>
            </div>
          ))}
        </div>
      )}
    </Page>
  );
}
