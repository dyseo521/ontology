"use client";

import {
  CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

export default function BacktestChart({
  data,
}: {
  data: { dates: string[]; strategy: number[]; baseline: number[] };
}) {
  const rows = data.dates.map((d, i) => ({
    date: d, strategy: data.strategy[i], baseline: data.baseline[i],
  }));
  const step = Math.max(1, Math.floor(data.dates.length / 6));
  return (
    <ResponsiveContainer width="100%" height={240}>
      <LineChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
        <CartesianGrid stroke="#f1f1f1" vertical={false} />
        <XAxis dataKey="date" ticks={data.dates.filter((_, i) => i % step === 0)}
               tickLine={false} axisLine={{ stroke: "#e6e6e6" }}
               tick={{ fontSize: 11, fontFamily: "var(--font-mono)" }} />
        <YAxis width={52} tickFormatter={(v: number) => v.toFixed(2)} tickLine={false} axisLine={false}
               tick={{ fontSize: 11, fontFamily: "var(--font-mono)" }} domain={["auto", "auto"]} />
        <Tooltip formatter={(v, name) => [(v as number).toFixed(3), name === "strategy" ? "전략" : "보유 지속"]}
                 contentStyle={{ border: "1px solid #e6e6e6", borderRadius: 8, fontSize: 13 }} />
        <Legend formatter={(v) => (v === "strategy" ? "제안 전략" : "보유 지속(베이스라인)")}
                wrapperStyle={{ fontSize: 13 }} />
        <Line type="monotone" dataKey="baseline" stroke="#b8b8b8" strokeWidth={1.4} dot={false} />
        <Line type="monotone" dataKey="strategy" stroke="#000000" strokeWidth={1.8} dot={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}
