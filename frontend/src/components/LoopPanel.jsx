import Panel from './Panel'
import { ROLES, loopStatus, ROLE_BORDER, ROLE_TEXT } from '../lib/format'

function RoleCard({ role, status }) {
  const on = status != null
  return (
    <div
      className={
        'flex-1 rounded-lg border bg-panel2 p-3 transition-opacity ' +
        (on ? 'opacity-100 ' + ROLE_BORDER[role.color] : 'border-line opacity-40')
      }
    >
      <div className={'text-[13px] font-semibold ' + (on ? ROLE_TEXT[role.color] : 'text-ink')}>{role.n}</div>
      <div className="mb-2 mt-0.5 min-h-[32px] text-[11.5px] leading-snug text-muted">{role.desc}</div>
      <div className="text-xs tabular-nums text-ink">{on ? status : '—'}</div>
    </div>
  )
}

export default function LoopPanel({ timeline }) {
  const s = loopStatus(timeline)
  const items = []
  ROLES.forEach((r, i) => {
    items.push(<RoleCard key={r.k} role={r} status={s[r.k]} />)
    if (i < ROLES.length - 1)
      items.push(
        <div key={'arr' + i} className="flex items-center justify-center px-2.5 text-muted">
          →
        </div>,
      )
  })
  return (
    <Panel title="The loop" hint="four roles collaborate on every task — click a task to trace its path">
      <div className="flex flex-col items-stretch gap-2 p-3 md:flex-row md:gap-0">{items}</div>
    </Panel>
  )
}
