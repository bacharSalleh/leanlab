// The agent transcript across all sessions. Content only — caller wraps in a Panel.
import { evMeta, fmtK } from '../lib/format'

function Ev({ ev }) {
  if (ev.kind === 'divider') {
    return (
      <div className="my-3 flex items-center gap-2.5 text-[11px] uppercase tracking-wider text-muted before:h-px before:flex-1 before:bg-line before:content-[''] after:h-px after:flex-1 after:bg-line after:content-['']">
        {ev.text}
        {ev.tokens ? ' · ' + fmtK(ev.tokens) + ' tok' : ''}
      </div>
    )
  }
  const m = evMeta(ev)
  const lbl = <span className="mb-0.5 block text-[10px] text-muted">{(ev.kind || 'msg') + (m ? ' · ' + m : '')}</span>
  const base = 'mb-2 max-h-[260px] overflow-auto whitespace-pre-wrap break-words rounded-lg px-2.5 py-2'
  if (ev.kind === 'tool')
    return (
      <div className={base + ' border border-[#332a4a] bg-[#16121f] font-mono text-xs'}>
        {lbl}
        <span className="font-semibold text-purple">{ev.name}</span> → {ev.text}
      </div>
    )
  if (ev.kind === 'result')
    return (
      <div className={base + ' border border-line bg-[#0e1216] font-mono text-xs text-muted'}>
        {lbl}
        {ev.text}
      </div>
    )
  if (ev.kind === 'user')
    return (
      <div className={base + ' border border-[#1f3a5f] bg-[#0e1a2b]'}>
        {lbl}
        {ev.text}
      </div>
    )
  return (
    <div className={base + ' bg-panel2'}>
      {lbl}
      {ev.text}
    </div>
  )
}

export default function AgentChat({ events }) {
  if (!events || !events.length) return <div className="italic text-muted">No agent activity captured yet.</div>
  return events.map((ev, i) => <Ev key={i} ev={ev} />)
}
