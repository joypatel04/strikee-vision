import { Suspense } from "react";
import LoginForm from "./LoginForm";

export const dynamic = "force-dynamic";

export default function LoginPage() {
  return (
    <Suspense fallback={<div className="login-wrap"><div className="card login-card">Loading…</div></div>}>
      <LoginForm />
    </Suspense>
  );
}
