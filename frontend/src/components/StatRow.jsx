import { fmtK } from '../lib/format'

function StatCard({ label, value, tone = '' }) {
  return (
    <div className="rounded-xl border border-line bg-panel px-4 py-3">
      <div className="text-[11px] uppercase tracking-wide text-muted">{label}</div>
      <div className={'mt-0.5 text-[26px] font-semibold tabular-nums ' + tone}>{value}</div>
    </div>
  )
}

export default function StatRow({ totals: t }) {
  const z = t || {}
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      <StatCard label="Tasks" value={z.tasks ?? '—'} />
      <StatCard label="Merged" value={z.merged ?? '—'} tone="text-good" />
      <StatCard label="Success" value={z.success == null ? '—' : z.success + '%'} />
      <StatCard label="Open" value={z.open ?? '—'} tone="text-amber" />
      <StatCard label="Tokens" value={fmtK(z.tokens)} />
      <StatCard label="Cost" value={'$' + (z.cost || 0).toFixed(2)} />
    </div>
  )
}
