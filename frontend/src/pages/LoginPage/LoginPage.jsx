import { useState } from "react";
import { useNavigate, useLocation, Link } from "react-router-dom";
import PageHeader from "../../components/ui/PageHeader";
import Page from "../../components/layout/Page";
import Button from "../../components/ui/Button";
import AuthPasswordField from "../../components/shared/AuthPasswordField";
import { IconUser } from "../../components/ui/icons";
import { useAuth } from "../../hooks/useAuth.js";
import "./LoginPage.css";

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [personalId, setPersonalId] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(personalId, password);
      const from = location.state?.from?.pathname ?? "/";
      navigate(from, { replace: true });
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <Page>
      <div className="auth-shell-container">
        <div className="auth-shell">
          <PageHeader
            title="התחברות"
            subtitle="התחברו עם תעודת הזהות והסיסמה שלכם."
          />

          <form className="auth-form card" onSubmit={handleSubmit}>
            <label className="auth-field">
              <span className="auth-label">מספר אישי</span>
              <div className="auth-input-wrap">
                <span className="auth-input-icon" aria-hidden="true">
                  <IconUser size={17} />
                </span>
                <input
                  className="auth-input"
                  type="text"
                  value={personalId}
                  onChange={(e) => setPersonalId(e.target.value)}
                  autoComplete="username"
                  required
                />
              </div>
            </label>

            <AuthPasswordField
              label="סיסמה"
              value={password}
              onChange={setPassword}
              autoComplete="current-password"
            />

            {error && (
              <p className="form-error" role="alert">
                {error}
              </p>
            )}

            <Button
              type="submit"
              variant="primary"
              size="lg"
              className="auth-submit"
              disabled={loading}
            >
              {loading ? "מתחבר…" : "התחברות"}
            </Button>

            <div className="auth-divider" />

            <p className="auth-alt">
              אין לך חשבון? <Link to="/register">הרשמה</Link>
            </p>
          </form>
        </div>
      </div>
    </Page>
  );
}
