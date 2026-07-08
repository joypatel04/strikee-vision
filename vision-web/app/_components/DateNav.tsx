"use client";

import { useRouter } from "next/navigation";
import { ChevronLeft, ChevronRight, CalendarDays } from "lucide-react";
import { Button } from "@/components/ui/button";

function shift(date: string, days: number): string {
  const d = new Date(date + "T00:00:00");
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

export default function DateNav({ date, today }: { date: string; today: string }) {
  const router = useRouter();
  const go = (d: string) => router.push(`/?date=${d}`);

  return (
    <div className="flex items-center gap-1.5">
      <Button variant="outline" size="icon" onClick={() => go(shift(date, -1))} aria-label="Previous day">
        <ChevronLeft className="h-4 w-4" />
      </Button>
      <div className="relative flex items-center">
        <CalendarDays className="pointer-events-none absolute left-3 h-4 w-4 text-muted-foreground" />
        <input
          type="date"
          value={date}
          max={today}
          onChange={(e) => go(e.target.value)}
          className="h-9 rounded-md border border-input bg-background/60 pl-9 pr-3 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [color-scheme:dark]"
        />
      </div>
      <Button
        variant="outline"
        size="icon"
        onClick={() => go(shift(date, 1))}
        disabled={date >= today}
        aria-label="Next day"
      >
        <ChevronRight className="h-4 w-4" />
      </Button>
      {date !== today && (
        <Button variant="ghost" size="sm" onClick={() => go(today)}>Today</Button>
      )}
    </div>
  );
}
