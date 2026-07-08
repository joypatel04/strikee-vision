import { PlugZap, Cctv } from "lucide-react";
import Topbar from "../_components/Topbar";
import MappingForm from "./MappingForm";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
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
      <Topbar />
      <main className="mx-auto max-w-3xl space-y-6 px-4 py-6">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Setup</h1>
          <p className="text-sm text-muted-foreground">
            Map each camera table to its Strikee facility. Do this once — reconciliation keys off it.
          </p>
        </div>

        {(!hasTurso() || !hasSupabase()) && (
          <Card className="border-warning/30">
            <CardContent className="flex items-start gap-3 pt-5">
              <PlugZap className="mt-0.5 h-5 w-5 text-warning" />
              <div className="text-sm">
                Configure <code className="rounded bg-muted px-1">TURSO_*</code> (tracked tables) and{" "}
                <code className="rounded bg-muted px-1">SUPABASE_*</code> (Strikee facilities) to load the lists.
              </div>
            </CardContent>
          </Card>
        )}

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Camera table → Strikee facility</CardTitle>
            <CardDescription>
              {facilities.length} facilities · {assets.length} tracked tables
            </CardDescription>
          </CardHeader>
          <CardContent>
            {assets.length === 0 ? (
              <div className="flex flex-col items-center gap-3 py-10 text-center">
                <span className="grid h-11 w-11 place-items-center rounded-full bg-secondary">
                  <Cctv className="h-5 w-5 text-muted-foreground" />
                </span>
                <p className="max-w-sm text-sm text-muted-foreground">
                  No tracked tables found in Turso yet. Once the Vision box has run and synced,
                  your tables appear here to map.
                </p>
              </div>
            ) : (
              <MappingForm assets={assets} facilities={facilities} initial={mapping} />
            )}
          </CardContent>
        </Card>
      </main>
    </>
  );
}
