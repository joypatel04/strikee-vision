import Link from "next/link";
import LogoutButton from "../_components/LogoutButton";
import MappingForm from "./MappingForm";
import { listAssets } from "@/lib/turso";
import { listFacilities } from "@/lib/supabase";
import { getMapping } from "@/lib/mapping";
import { SHOP_ID, hasSupabase, hasTurso } from "@/lib/config";

export const dynamic = "force-dynamic";

export default async function SetupPage() {
  const [assets, facilities, mapping] = await Promise.all([
    listAssets(),
    listFacilities(SHOP_ID),
    getMapping(),
  ]);

  return (
    <>
      <header>
        <h1>Strikee Vision · Setup</h1>
        <span className="muted">map each camera table → Strikee facility</span>
        <div className="spacer" />
        <Link href="/" className="pill">Dashboard</Link>
        <LogoutButton />
      </header>
      <main>
        {(!hasTurso() || !hasSupabase()) && (
          <div className="card warn">
            Configure <code>TURSO_*</code> (tracked tables) and{" "}
            <code>SUPABASE_*</code> (Strikee facilities) to load the lists.
          </div>
        )}
        <div className="card">
          <h2>Camera table → Strikee facility</h2>
          {assets.length === 0 ? (
            <p className="muted">
              No tracked tables found in Turso yet. Once the Vision box has run and
              synced, your tables (assets) appear here to map.
            </p>
          ) : (
            <MappingForm
              assets={assets}
              facilities={facilities}
              initial={mapping}
            />
          )}
        </div>
      </main>
    </>
  );
}
