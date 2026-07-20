import PageHeader from "../../components/ui/PageHeader";
import Page from "../../components/layout/Page";
import Pill from "../../components/ui/Pill";
import Button from "../../components/ui/Button";
import LoaderLayout from "../../components/ui/LoaderLayout/LoaderLayout.jsx";
import EmptyState from "../../components/ui/EmptyState";
import { useUserManagement } from "./useUserManagement.js";
import "./UserManagementPage.css";

const ROLE_LABELS = { user: "משתמש", editor: "עורך", admin: "מנהל" };
const ROLE_TONES = { user: "default", editor: "accent", admin: "accent" };

export default function UserManagementPage() {
  const { users, query, setQuery, loading, error, promote, demote } =
    useUserManagement();

  const total = users.length;
  const editorCount = users.filter((u) => u.role === "editor").length;
  const adminCount = users.filter((u) => u.role === "admin").length;

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
        <input
          className="auth-input user-mgmt-search"
          type="text"
          placeholder="חיפוש לפי מספר אישי…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
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
            <span>מספר אישי</span>
            <span>שם</span>
            <span>הרשאה</span>
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
