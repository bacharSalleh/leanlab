import { BADGE } from '../lib/format'

export default function Badge({ status }) {
  return (
    <span
      className={
        'rounded-full px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide ' +
        (BADGE[status] || 'bg-panel2 text-muted')
      }
    >
      {status}
    </span>
  )
}
