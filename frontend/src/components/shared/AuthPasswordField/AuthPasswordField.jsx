import { useState } from "react";
import IconButton from "../../ui/IconButton";
import { IconLock, IconEye, IconEyeOff } from "../../ui/icons";

export default function AuthPasswordField({ label, value, onChange, autoComplete }) {
  const [visible, setVisible] = useState(false);

  return (
    <label className="auth-field">
      <span className="auth-label">{label}</span>
      <div className="auth-input-wrap">
        <span className="auth-input-icon" aria-hidden="true">
          <IconLock size={17} />
        </span>
        <input
          className="auth-input"
          type={visible ? "text" : "password"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          autoComplete={autoComplete}
          required
        />
        <IconButton
          size="sm"
          className="auth-input-toggle"
          ariaLabel={visible ? "הסתר סיסמה" : "הצג סיסמה"}
          onClick={() => setVisible((v) => !v)}
        >
          {visible ? <IconEyeOff size={16} /> : <IconEye size={16} />}
        </IconButton>
      </div>
    </label>
  );
}
