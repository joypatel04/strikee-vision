"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { format } from "date-fns";
import { ChevronLeft, ChevronRight, CalendarDays } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

function toStr(d: Date): string {
  return format(d, "yyyy-MM-dd");
}
function shift(date: string, days: number): string {
  const d = new Date(date + "T00:00:00");
  d.setDate(d.getDate() + days);
  return toStr(d);
}

export default function DateNav({ date, today }: { date: string; today: string }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const selected = new Date(date + "T00:00:00");
  const maxDate = new Date(today + "T00:00:00");
  const isToday = date === today;

  const go = (d: string) => router.push(`/?date=${d}`);

  return (
    <div className="flex items-center gap-1.5">
      <Button variant="outline" size="icon" onClick={() => go(shift(date, -1))} aria-label="Previous day">
        <ChevronLeft className="h-4 w-4" />
      </Button>

      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button variant="outline" className="min-w-[168px] justify-start font-normal">
            <CalendarDays className="h-4 w-4 text-muted-foreground" />
            {isToday ? "Today" : format(selected, "EEE, d MMM yyyy")}
          </Button>
        </PopoverTrigger>
        <PopoverContent align="end">
          <Calendar
            mode="single"
            selected={selected}
            defaultMonth={selected}
            disabled={{ after: maxDate }}
            onSelect={(d) => {
              if (d) {
                setOpen(false);
                go(toStr(d));
              }
            }}
          />
        </PopoverContent>
      </Popover>

      <Button
        variant="outline"
        size="icon"
        onClick={() => go(shift(date, 1))}
        disabled={isToday}
        aria-label="Next day"
      >
        <ChevronRight className="h-4 w-4" />
      </Button>

      {!isToday && (
        <Button variant="ghost" size="sm" onClick={() => go(today)}>Today</Button>
      )}
    </div>
  );
}
