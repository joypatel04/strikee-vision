import { cn } from "@/lib/utils";
import { Card } from "@/components/ui/card";

export function StatCard({
  label,
  value,
  sub,
  icon: Icon,
  tone = "default",
}: {
  label: string;
  value: string | number;
  sub?: string;
  icon: React.ComponentType<{ className?: string }>;
  tone?: "default" | "success" | "warning" | "danger";
}) {
  const toneClass = {
    default: "text-foreground",
    success: "text-primary",
    warning: "text-warning",
    danger: "text-destructive",
  }[tone];
  const iconBg = {
    default: "bg-secondary text-muted-foreground",
    success: "bg-primary/15 text-primary",
    warning: "bg-warning/15 text-warning",
    danger: "bg-destructive/15 text-destructive",
  }[tone];

  return (
    <Card className="p-5 animate-fade-in">
      <div className="flex items-start justify-between">
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {label}
        </span>
        <span className={cn("grid h-8 w-8 place-items-center rounded-lg", iconBg)}>
          <Icon className="h-4 w-4" />
        </span>
      </div>
      <div className={cn("mt-3 text-3xl font-semibold tabular-nums tracking-tight", toneClass)}>
        {value}
      </div>
      {sub && <div className="mt-1 text-xs text-muted-foreground">{sub}</div>}
    </Card>
  );
}
