"use client";

import {
  Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

export interface ChartRow { label: string; tracked: number; billed: number; }

export default function ReconChart({ data }: { data: ChartRow[] }) {
  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={data} barGap={6} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="hsl(240 5% 16%)" vertical={false} />
        <XAxis dataKey="label" stroke="hsl(240 5% 55%)" fontSize={12} tickLine={false} axisLine={false} />
        <YAxis stroke="hsl(240 5% 55%)" fontSize={12} tickLine={false} axisLine={false} allowDecimals={false} />
        <Tooltip
          cursor={{ fill: "hsl(240 5% 12%)" }}
          contentStyle={{
            background: "hsl(240 10% 7%)",
            border: "1px solid hsl(240 5% 16%)",
            borderRadius: 10,
            fontSize: 12,
            color: "hsl(0 0% 98%)",
          }}
        />
        <Legend wrapperStyle={{ fontSize: 12 }} iconType="circle" />
        <Bar dataKey="tracked" name="Tracked (camera)" fill="hsl(152 66% 46%)" radius={[4, 4, 0, 0]} />
        <Bar dataKey="billed" name="Billed (Strikee)" fill="hsl(217 91% 60%)" radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}
