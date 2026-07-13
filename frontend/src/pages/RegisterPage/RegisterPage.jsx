import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import PageHeader from "../../components/ui/PageHeader";
import Page from "../../components/layout/Page";
import Button from "../../components/ui/Button";
import AuthPasswordField from "../../components/shared/AuthPasswordField";
import { IconUser } from "../../components/ui/icons";
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
      <div className="auth-shell-container">
        <div className="auth-shell">
          <PageHeader title="הרשמה" subtitle="פתחו חשבון כדי להתחיל." />

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

            <div className="auth-field-row">
              <label className="auth-field">
                <span className="auth-label">שם פרטי</span>
                <div className="auth-input-wrap">
                  <input
                    className="auth-input"
                    type="text"
                    value={firstName}
                    onChange={(e) => setFirstName(e.target.value)}
                    autoComplete="given-name"
                    required
                  />
                </div>
              </label>

              <label className="auth-field">
                <span className="auth-label">שם משפחה</span>
                <div className="auth-input-wrap">
                  <input
                    className="auth-input"
                    type="text"
                    value={lastName}
                    onChange={(e) => setLastName(e.target.value)}
                    autoComplete="family-name"
                    required
                  />
                </div>
              </label>
            </div>

            <AuthPasswordField
              label="סיסמה"
              value={password}
              onChange={setPassword}
              autoComplete="new-password"
            />

            <AuthPasswordField
              label="אימות סיסמה"
              value={password2}
              onChange={setPassword2}
              autoComplete="new-password"
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
              {loading ? "נרשם…" : "הרשמה"}
            </Button>

            <div className="auth-divider" />

            <p className="auth-alt">
              כבר יש לך חשבון? <Link to="/login">התחברות</Link>
            </p>
          </form>
        </div>
      </div>
    </Page>
  );
}
