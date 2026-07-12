import { useState } from "react";
import { useNavigate, useLocation, Link } from "react-router-dom";
import PageHeader from "../../components/ui/PageHeader";
import Page from "../../components/layout/Page";
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
      <PageHeader
        title="התחברות"
        subtitle="התחברו עם תעודת הזהות והסיסמה שלכם."
      />

      <form className="auth-form card" onSubmit={handleSubmit}>
        <label className="auth-field">
          <span className="auth-label">מספר אישי</span>
          <input
            className="auth-input"
            type="text"
            value={personalId}
            onChange={(e) => setPersonalId(e.target.value)}
            autoComplete="username"
            required
          />
        </label>

        <label className="auth-field">
          <span className="auth-label">סיסמה</span>
          <input
            className="auth-input"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>

        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}

        <button
          type="submit"
          className="btn btn-primary auth-submit"
          disabled={loading}
        >
          {loading ? "מתחבר…" : "התחברות"}
        </button>

        <p className="auth-alt">
          אין לך חשבון? <Link to="/register">הרשמה</Link>
        </p>
      </form>
    </Page>
  );
}
