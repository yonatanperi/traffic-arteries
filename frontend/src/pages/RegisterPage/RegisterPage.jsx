import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import PageHeader from "../../components/ui/PageHeader";
import Page from "../../components/layout/Page";
import { useAuth } from "../../hooks/useAuth.js";
import "../LoginPage/LoginPage.css";

export default function RegisterPage() {
  const { register } = useAuth();
  const navigate = useNavigate();

  const [personalId, setPersonalId] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [password, setPassword] = useState("");
  const [password2, setPassword2] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await register({
        personal_id: personalId,
        first_name: firstName,
        last_name: lastName,
        password,
        password2,
      });
      navigate("/", { replace: true });
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <Page>
      <PageHeader title="הרשמה" subtitle="פתחו חשבון כדי להתחיל." />

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
          <span className="auth-label">שם פרטי</span>
          <input
            className="auth-input"
            type="text"
            value={firstName}
            onChange={(e) => setFirstName(e.target.value)}
            autoComplete="given-name"
            required
          />
        </label>

        <label className="auth-field">
          <span className="auth-label">שם משפחה</span>
          <input
            className="auth-input"
            type="text"
            value={lastName}
            onChange={(e) => setLastName(e.target.value)}
            autoComplete="family-name"
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
            autoComplete="new-password"
            required
          />
        </label>

        <label className="auth-field">
          <span className="auth-label">אימות סיסמה</span>
          <input
            className="auth-input"
            type="password"
            value={password2}
            onChange={(e) => setPassword2(e.target.value)}
            autoComplete="new-password"
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
          {loading ? "נרשם…" : "הרשמה"}
        </button>

        <p className="auth-alt">
          כבר יש לך חשבון? <Link to="/login">התחברות</Link>
        </p>
      </form>
    </Page>
  );
}
