import Link from "next/link";
import {
  Wallet, Banknote, CreditCard, HandCoins,
  ArrowRight, Radio, CircleCheck, PlugZap, Target,
} from "lucide-react";
import Topbar from "./_components/Topbar";
import { StatCard } from "./_components/StatCard";
import DateNav from "./_components/DateNav";
import ReconChart from "./_components/ReconChart";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table, TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { reconcile } from "@/lib/reconcile";
import { cashbookTotal } from "@/lib/supabase";
import { SHOP_ID, hasSupabase, hasTurso, currentBusinessDate } from "@/lib/config";

export const dynamic = "force-dynamic";

const inr = (n: number) => "₹" + n.toLocaleString("en-IN", { maximumFractionDigits: 0 });

export default async function Dashboard({
  searchParams,
}: {
  searchParams: { date?: string };
}) {
  const today = currentBusinessDate();
  const date = searchParams.date || today;
  const [r, cash] = await Promise.all([reconcile(date), cashbookTotal(SHOP_ID, date)]);
  const configured = hasTurso() && hasSupabase();

  return (
    <>
      <Topbar />
      <main className="mx-auto max-w-6xl space-y-6 px-4 py-6">
        {/* header row */}
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-xl font-semibold tracking-tight">Reconciliation</h1>
            <p className="text-sm text-muted-foreground">
              Games our cameras tracked vs what Strikee billed · Snooker (shop 36)
              <span className="ml-1 text-muted-foreground/70">· business day 5 AM–5 AM IST</span>
            </p>
          </div>
          <DateNav date={date} today={today} />
        </div>

        {/* KPI cards — the SAME figures as the Strikee cashbook */}
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <StatCard label="Today's balance" value={inr(cash?.todaysBalance ?? 0)} icon={Wallet} tone="success" sub="cash + UPI/card collected" />
          <StatCard label="Cash in hand" value={inr(cash?.cashInHand ?? 0)} icon={Banknote} />
          <StatCard label="UPI / Card" value={inr(cash?.upiCardNet ?? 0)} icon={CreditCard} />
          <StatCard
            label="Credit used"
            value={inr(cash?.credit ?? 0)}
            icon={HandCoins}
            tone={(cash?.credit ?? 0) > 0 ? "warning" : "default"}
            sub="unpaid tabs"
          />
        </div>

        {/* not configured */}
        {!configured && (
          <Card className="border-warning/30">
            <CardContent className="flex items-start gap-3 pt-5">
              <PlugZap className="mt-0.5 h-5 w-5 text-warning" />
              <div>
                <div className="font-medium">Data sources not connected</div>
                <p className="text-sm text-muted-foreground">
                  Set the <code className="rounded bg-muted px-1">TURSO_*</code> and{" "}
                  <code className="rounded bg-muted px-1">SUPABASE_*</code> env vars in Vercel, then redeploy.
                </p>
              </div>
            </CardContent>
          </Card>
        )}

        {/* configured but no mapping */}
        {configured && !r.mapped && (
          <Card>
            <CardContent className="flex flex-col items-center gap-3 py-14 text-center">
              <span className="grid h-12 w-12 place-items-center rounded-full bg-primary/15">
                <Radio className="h-6 w-6 text-primary" />
              </span>
              <div className="text-lg font-medium">Map your tables to get started</div>
              <p className="max-w-md text-sm text-muted-foreground">
                Link each camera table to its Strikee facility once. Reconciliation then
                appears here automatically as the venue box syncs game data.
              </p>
              <Button asChild className="mt-1">
                <Link href="/setup">Go to setup <ArrowRight className="h-4 w-4" /></Link>
              </Button>
            </CardContent>
          </Card>
        )}

        {/* the reconciliation */}
        {r.mapped && (
          <div className="grid gap-6 lg:grid-cols-5">
            <Card className="lg:col-span-3">
              <CardHeader className="flex-row items-start justify-between space-y-0">
                <div className="space-y-1">
                  <CardTitle className="text-base">Games by table</CardTitle>
                  <CardDescription>Detected vs billed · {date}</CardDescription>
                </div>
                <div className="flex flex-wrap items-center gap-1.5">
                  <Badge variant="outline"><Target className="h-3 w-3" /> {r.totals.trackedGames} tracked</Badge>
                  <Badge variant="outline">{r.totals.billedGames} billed</Badge>
                  <Badge variant={r.totals.gap > 0 ? "warning" : "success"}>
                    gap {r.totals.gap > 0 ? `+${r.totals.gap}` : r.totals.gap}
                  </Badge>
                </div>
              </CardHeader>
              <CardContent className="p-0">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Table</TableHead>
                      <TableHead className="text-right">Tracked</TableHead>
                      <TableHead className="text-right">Billed</TableHead>
                      <TableHead className="text-right">Gap</TableHead>
                      <TableHead className="text-right">In use</TableHead>
                      <TableHead className="text-right">Flag</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {r.rows.map((row) => (
                      <TableRow key={row.assetId}>
                        <TableCell className="font-medium">{row.label}</TableCell>
                        <TableCell className="text-right tabular-nums">{row.trackedGames}</TableCell>
                        <TableCell className="text-right tabular-nums">{row.billedGames}</TableCell>
                        <TableCell className="text-right tabular-nums font-medium">
                          {row.gap > 0 ? `+${row.gap}` : row.gap}
                        </TableCell>
                        <TableCell className="text-right tabular-nums text-muted-foreground">
                          {row.inUseMinutes}m
                        </TableCell>
                        <TableCell className="text-right">
                          {row.status === "leak" && <Badge variant="destructive">played &gt; billed</Badge>}
                          {row.status === "over" && <Badge variant="warning">billed &gt; tracked</Badge>}
                          {row.status === "ok" && (
                            <Badge variant="success"><CircleCheck className="h-3 w-3" /> match</Badge>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                  <TableFooter>
                    <TableRow>
                      <TableCell className="font-semibold">Total</TableCell>
                      <TableCell className="text-right tabular-nums font-semibold">{r.totals.trackedGames}</TableCell>
                      <TableCell className="text-right tabular-nums font-semibold">{r.totals.billedGames}</TableCell>
                      <TableCell className="text-right tabular-nums font-semibold">
                        {r.totals.gap > 0 ? `+${r.totals.gap}` : r.totals.gap}
                      </TableCell>
                      <TableCell />
                      <TableCell />
                    </TableRow>
                  </TableFooter>
                </Table>
              </CardContent>
            </Card>

            <Card className="lg:col-span-2">
              <CardHeader>
                <CardTitle className="text-base">Tracked vs billed</CardTitle>
                <CardDescription>Per table, {date}.</CardDescription>
              </CardHeader>
              <CardContent>
                {r.rows.length ? (
                  <ReconChart data={r.rows.map((x) => ({ label: x.label, tracked: x.trackedGames, billed: x.billedGames }))} />
                ) : (
                  <p className="py-10 text-center text-sm text-muted-foreground">No data for this day.</p>
                )}
                <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
                  <span className="text-destructive">played &gt; billed</span> = games seen but not
                  billed (possible leakage). <span className="text-warning">billed &gt; tracked</span> =
                  more billed than seen (e.g. pool on a shared table, or a missed detection). The
                  consistent trend is the signal — exact daily parity isn&apos;t expected.
                </p>
              </CardContent>
            </Card>
          </div>
        )}
      </main>
    </>
  );
}
