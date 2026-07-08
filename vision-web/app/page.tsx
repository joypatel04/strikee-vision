import Link from "next/link";
import LogoutButton from "./_components/LogoutButton";
import { reconcile } from "@/lib/reconcile";
import { hasSupabase, hasTurso, todayIST } from "@/lib/config";

export const dynamic = "force-dynamic";

const inr = (n: number) =>
  "₹" + n.toLocaleString("en-IN", { maximumFractionDigits: 0 });

export default async function Dashboard({
  searchParams,
}: {
  searchParams: { date?: string };
}) {
  const date = searchParams.date || todayIST();
  const r = await reconcile(date);
  const configured = hasTurso() && hasSupabase();

  return (
    <>
      <header>
        <h1>Strikee Vision · Reconciliation</h1>
        <span className="muted">tracked play vs billed — snooker</span>
        <div className="spacer" />
        <Link href="/setup" className="pill">Setup</Link>
        <LogoutButton />
      </header>
      <main>
        <div className="card">
          <form className="row" method="get">
            <div>
              <label>Date</label>
              <input type="date" name="date" defaultValue={date} />
            </div>
            <div style={{ alignSelf: "end" }}>
              <button type="submit">View</button>
            </div>
            <div className="spacer" />
            <div style={{ textAlign: "right" }}>
              <label>Revenue (billed)</label>
              <div style={{ fontSize: 20, fontWeight: 700 }}>{inr(r.totals.revenue)}</div>
            </div>
          </form>
        </div>

        {!configured && (
          <div className="card warn">
            Data sources not configured yet. Set <code>TURSO_*</code> and{" "}
            <code>SUPABASE_*</code> env vars (see <code>.env.example</code>).
          </div>
        )}

        {configured && !r.mapped && (
          <div className="card">
            No tables mapped yet. Go to <Link href="/setup">Setup</Link> to map each
            camera table to its Strikee facility — then reconciliation appears here.
          </div>
        )}

        {r.mapped && (
          <div className="card">
            <h2>Games — detected vs billed · {date}</h2>
            <table>
              <thead>
                <tr>
                  <th>Table</th>
                  <th className="num">Tracked</th>
                  <th className="num">Billed</th>
                  <th className="num">Gap</th>
                  <th className="num">In use</th>
                  <th className="num">Revenue</th>
                  <th>Flag</th>
                </tr>
              </thead>
              <tbody>
                {r.rows.map((row) => (
                  <tr key={row.assetId}>
                    <td>{row.label}</td>
                    <td className="num">{row.trackedGames}</td>
                    <td className="num">{row.billedGames}</td>
                    <td className="num">{row.gap > 0 ? `+${row.gap}` : row.gap}</td>
                    <td className="num">{row.inUseMinutes}m</td>
                    <td className="num">{inr(row.revenue)}</td>
                    <td>
                      {row.status === "leak" && (
                        <span className="pill leak">played &gt; billed</span>
                      )}
                      {row.status === "over" && (
                        <span className="pill warn">billed &gt; tracked</span>
                      )}
                      {row.status === "ok" && <span className="pill ok">match</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <th>Total</th>
                  <th className="num">{r.totals.trackedGames}</th>
                  <th className="num">{r.totals.billedGames}</th>
                  <th className="num">{r.totals.gap > 0 ? `+${r.totals.gap}` : r.totals.gap}</th>
                  <th></th>
                  <th className="num">{inr(r.totals.revenue)}</th>
                  <th></th>
                </tr>
              </tfoot>
            </table>
            <p className="muted" style={{ marginTop: 12, fontSize: 12 }}>
              <b>played &gt; billed</b> = games we detected that weren&apos;t billed
              (potential leakage). <b>billed &gt; tracked</b> = more billed than seen
              (e.g. pool on a shared table, or a missed detection). A consistent gap
              is the signal — exact per-day parity isn&apos;t expected.
            </p>
          </div>
        )}
      </main>
    </>
  );
}
