import { useState, type FormEvent } from "react";
import { login, type Session } from "../api";
import { Mark } from "./Rail";

export default function Login({ onLogin, notice }: { onLogin: (session: Session) => void; notice?: string | null }) {
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onLogin(await login(name.trim(), password));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login">
      <form className="login-sheet" onSubmit={submit}>
        <header className="login-head">
          <Mark size={34} />
          <div>
            <h1>Инспектор ИИ</h1>
            <div className="sub">Сверка ПД · РД · ИД</div>
          </div>
        </header>
        {notice && <div className="note-line">{notice}</div>}
        <label className="field">
          <span className="k">Логин</span>
          <input id="login-name" value={name} onChange={(e) => setName(e.target.value)} autoComplete="username" required />
        </label>
        <label className="field">
          <span className="k">Пароль</span>
          <input
            id="login-password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>
        {error && <div className="alert">{error}</div>}
        <button className="btn btn-primary" type="submit" disabled={busy}>
          {busy ? "Вход…" : "Войти"}
        </button>
        <p className="hint">Учётные записи стенда задаются переменной AUTH_USERS сервиса.</p>
      </form>
    </div>
  );
}
