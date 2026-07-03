"use client";

import {
  Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import type { RiskSeries } from "@/lib/data";
import { fmtKrw, fmtPct } from "@/lib/format";

const INK = "#000000";
const LIME = "#dceeb1";
const CORAL = "#f3c9b6";

function tickDates(dates: string[]): string[] {
  const step = Math.max(1, Math.floor(dates.length / 6));
  return dates.filter((_, i) => i % step === 0);
}

export function PortfolioValueChart({ series }: { series: RiskSeries }) {
  const data = series.dates.map((d, i) => ({ date: d, value: series.totalValueBase[i] }));
  return (
    <ResponsiveContainer width="100%" height={320}>
      <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
        <defs>
          <linearGradient id="valueFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={LIME} stopOpacity={0.9} />
            <stop offset="100%" stopColor={LIME} stopOpacity={0.15} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="#f1f1f1" vertical={false} />
        <XAxis dataKey="date" ticks={tickDates(series.dates)} tickLine={false} axisLine={{ stroke: "#e6e6e6" }}
               tick={{ fontSize: 11, fontFamily: "var(--font-mono)", fill: INK }} />
        <YAxis width={72} tickFormatter={(v: number) => fmtKrw(v, true)} tickLine={false} axisLine={false}
               tick={{ fontSize: 11, fontFamily: "var(--font-mono)", fill: INK }}
               domain={["auto", "auto"]} />
        <Tooltip
          formatter={(v) => [fmtKrw(v as number), "평가액"]}
          contentStyle={{ border: "1px solid #e6e6e6", borderRadius: 8, fontSize: 13 }}
        />
        <Area type="monotone" dataKey="value" stroke={INK} strokeWidth={1.5}
              fill="url(#valueFill)" dot={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function DrawdownChart({ series }: { series: RiskSeries }) {
  const data = series.dates.map((d, i) => ({ date: d, dd: series.drawdown[i] }));
  return (
    <ResponsiveContainer width="100%" height={160}>
      <AreaChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 8 }}>
        <CartesianGrid stroke="#f1f1f1" vertical={false} />
        <XAxis dataKey="date" ticks={tickDates(series.dates)} tickLine={false} axisLine={{ stroke: "#e6e6e6" }}
               tick={{ fontSize: 11, fontFamily: "var(--font-mono)", fill: INK }} />
        <YAxis width={56} tickFormatter={(v: number) => fmtPct(v, 0)} tickLine={false} axisLine={false}
               tick={{ fontSize: 11, fontFamily: "var(--font-mono)", fill: INK }} />
        <Tooltip formatter={(v) => [fmtPct(v as number), "낙폭"]}
                 contentStyle={{ border: "1px solid #e6e6e6", borderRadius: 8, fontSize: 13 }} />
        <Area type="monotone" dataKey="dd" stroke="#b0532f" strokeWidth={1.2} fill={CORAL} fillOpacity={0.6} dot={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function PriceChart({ dates, close }: { dates: string[]; close: number[] }) {
  const data = dates.map((d, i) => ({ date: d, close: close[i] }));
  return (
    <ResponsiveContainer width="100%" height={280}>
      <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
        <CartesianGrid stroke="#f1f1f1" vertical={false} />
        <XAxis dataKey="date" ticks={tickDates(dates)} tickLine={false} axisLine={{ stroke: "#e6e6e6" }}
               tick={{ fontSize: 11, fontFamily: "var(--font-mono)", fill: INK }} />
        <YAxis width={64} tickFormatter={(v: number) => v.toLocaleString()} tickLine={false} axisLine={false}
               tick={{ fontSize: 11, fontFamily: "var(--font-mono)", fill: INK }} domain={["auto", "auto"]} />
        <Tooltip formatter={(v) => [(v as number).toLocaleString(), "종가"]}
                 contentStyle={{ border: "1px solid #e6e6e6", borderRadius: 8, fontSize: 13 }} />
        <Area type="monotone" dataKey="close" stroke={INK} strokeWidth={1.5} fill="#f7f7f5" dot={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}
