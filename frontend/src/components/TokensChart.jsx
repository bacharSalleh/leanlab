import Panel from './Panel'
import { fmtK, BAR } from '../lib/format'

export default function TokensChart({ tasks }) {
  const max = Math.max(1, ...tasks.map((t) => t.tokens || 0))
  return (
    <Panel title="Tokens by task" className="flex-1" bodyClass="max-h-[340px] overflow-auto p-3.5">
      {tasks.length === 0 ? (
        <div className="italic text-muted">No tasks yet</div>
      ) : (
        tasks.map((t) => (
          <div key={t.slug} className="mb-3.5">
            <div className="mb-1 flex justify-between gap-2.5 text-[12.5px]">
              <span className="truncate">{t.slug}</span>
              <span className="whitespace-nowrap tabular-nums text-muted">
                {fmtK(t.tokens)} tok · ${(t.cost || 0).toFixed(2)}
              </span>
            </div>
            <div className="h-4 overflow-hidden rounded bg-[#22262e]">
              <div
                className={'h-full rounded ' + (BAR[t.status] || 'bg-accent')}
                style={{ width: Math.round((100 * (t.tokens || 0)) / max) + '%', minWidth: '2px' }}
              />
            </div>
          </div>
        ))
      )}
    </Panel>
  )
}
