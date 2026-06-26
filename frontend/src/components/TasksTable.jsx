import Panel from './Panel'
import Badge from './Badge'
import { fmtK } from '../lib/format'

const ORDER = { merged: 0, "spec'd": 1, failed: 2 }

export default function TasksTable({ tasks, selected, sortCol, sortDir, onSort, onSelect }) {
  const rows = [...tasks].sort((a, b) => {
    let x = a[sortCol],
      y = b[sortCol]
    if (sortCol === 'status') {
      x = ORDER[x] ?? 9
      y = ORDER[y] ?? 9
    }
    if (typeof x === 'string') return sortDir * x.localeCompare(y)
    return sortDir * ((x || 0) - (y || 0))
  })

  const Th = ({ col, children, num }) => (
    <th
      onClick={() => onSort(col)}
      className={
        'sticky top-0 z-[1] cursor-pointer select-none border-b border-line bg-panel px-3.5 py-2.5 ' +
        'text-[11px] font-medium uppercase tracking-wide text-muted ' +
        (num ? 'text-right' : 'text-left')
      }
    >
      {children}
    </th>
  )

  return (
    <Panel title="Tasks" hint="click a row to inspect" className="flex-[2]" bodyClass="max-h-[340px] overflow-auto">
      <table className="w-full border-collapse text-[13px]">
        <thead>
          <tr>
            <Th col="slug">Task</Th>
            <Th col="status">Status</Th>
            <Th col="attempts" num>
              Attempts
            </Th>
            <Th col="tokens" num>
              Tokens
            </Th>
            <Th col="cost" num>
              Cost
            </Th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan="5" className="px-4 py-4 italic text-muted">
                No tasks yet — run leanlab spec.
              </td>
            </tr>
          ) : (
            rows.map((t) => (
              <tr
                key={t.slug}
                onClick={() => onSelect(t.slug)}
                className={
                  'cursor-pointer border-b border-line hover:bg-panel2 ' + (t.slug === selected ? 'bg-[#10243b]' : '')
                }
              >
                <td className="px-3.5 py-2.5">
                  <div className="font-semibold">{t.slug}</div>
                  <div className="mt-0.5 max-w-[380px] truncate text-xs text-muted">{t.spec}</div>
                </td>
                <td className="px-3.5 py-2.5">
                  <Badge status={t.status} />
                </td>
                <td className="px-3.5 py-2.5 text-right tabular-nums">{t.attempts == null ? '—' : t.attempts}</td>
                <td className="px-3.5 py-2.5 text-right tabular-nums">{fmtK(t.tokens)}</td>
                <td className="px-3.5 py-2.5 text-right tabular-nums">${(t.cost || 0).toFixed(4)}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </Panel>
  )
}
