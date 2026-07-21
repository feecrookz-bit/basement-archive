"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

export default function Login() {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const router = useRouter();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const r = await fetch(`${API}/api/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ password }),
      });
      if (r.ok) {
        router.push("/");
        router.refresh();
      } else {
        setError("Wrong password — the ledger forgives, the login does not.");
      }
    } catch {
      setError("API unreachable. Is the engine running?");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={submit}>
        <div className="brand" style={{ justifyContent: "center", marginBottom: 6 }}>
          <span className="bolt">⚡</span>
          <span style={{ fontSize: 18 }}>
            SENTINEL <span className="bot">Bot</span>
          </span>
        </div>
        <p className="muted" style={{ textAlign: "center", marginTop: 0 }}>
          discipline-enforcement engine · sign in to view
        </p>
        <input
          type="password"
          autoFocus
          placeholder="dashboard password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          data-testid="password"
        />
        <button type="submit" disabled={busy || !password} data-testid="signin">
          {busy ? "checking…" : "Sign in"}
        </button>
        {error && (
          <p className="login-error" data-testid="login-error">{error}</p>
        )}
        <p className="dim" style={{ fontSize: 11, textAlign: "center", marginBottom: 0 }}>
          read-only dashboard — no trading controls exist here by design
        </p>
      </form>
    </div>
  );
}
