import { useEffect, useState } from 'react'
import { useStream } from './hooks/useStream'
import { fmtK } from './lib/format'
import Header from './components/Header'
import StatRow from './components/StatRow'
import LoopPanel from './components/LoopPanel'
import TasksTable from './components/TasksTable'
import TokensChart from './components/TokensChart'
import Timeline from './components/Timeline'
import AgentChat from './components/AgentChat'
import Playbook from './components/Playbook'
import Panel from './components/Panel'

const qp = new URLSearchParams(location.search)
const FULL = qp.get('full') === '1'
const INIT_TASK = qp.get('task') || null

const chatMeta = (td) => (td?.tokens ? fmtK(td.tokens) + ' tok · ' : '') + '$' + (td?.cost || 0).toFixed(4)

export default function App() {
  const [selected, setSelected] = useState(INIT_TASK)
  const [sortCol, setSortCol] = useState('status')
  const [sortDir, setSortDir] = useState(1)
  const { state, task, connected } = useStream(selected)

  // On the dashboard, auto-select the most recent task once data arrives.
  useEffect(() => {
    if (!FULL && !selected && state?.tasks?.length) setSelected(state.tasks[state.tasks.length - 1].slug)
  }, [state, selected])

  const onSort = (c) => (c === sortCol ? setSortDir((d) => -d) : (setSortCol(c), setSortDir(1)))
  const openTask = (slug) => window.open('?task=' + encodeURIComponent(slug) + '&full=1', '_blank')

  // Dedicated full-screen page: just the big timeline + agent chat.
  if (FULL) {
    return (
      <div className="flex h-screen flex-col">
        <Header lab={state?.lab} connected={connected} full sub={selected ? 'task · ' + selected : 'task'} />
        <div className="flex min-h-0 flex-1 flex-col gap-4 p-4 lg:flex-row">
          <Panel title={'Timeline' + (task?.slug ? ' · ' + task.slug : '')} className="h-full flex-1" bodyClass="flex-1 overflow-auto p-3.5">
            <Timeline events={task?.timeline} status={task?.status} />
          </Panel>
          <Panel title="Agent chat" meta={chatMeta(task)} className="h-full flex-[2]" bodyClass="flex-1 overflow-auto p-3.5">
            <AgentChat events={task?.stream} />
          </Panel>
        </div>
      </div>
    )
  }

  const tasks = state?.tasks || []
  return (
    <div className="min-h-screen">
      <Header lab={state?.lab} connected={connected} />
      <div className="mx-auto flex max-w-[1360px] flex-col gap-4 px-5 py-4">
        <StatRow totals={state?.totals} />
        <LoopPanel timeline={selected ? task?.timeline : null} />

        <div className="flex flex-col gap-4 lg:flex-row">
          <TasksTable
            tasks={tasks}
            selected={selected}
            sortCol={sortCol}
            sortDir={sortDir}
            onSort={onSort}
            onSelect={setSelected}
          />
          <TokensChart tasks={tasks} />
        </div>

        {selected && task && (
          <div className="flex flex-col gap-4 lg:flex-row">
            <Panel
              title={'Timeline · ' + (task.slug || '')}
              className="h-[440px] flex-1"
              bodyClass="flex-1 overflow-auto p-3.5"
              right={
                <button
                  onClick={() => openTask(task.slug)}
                  title="Open this task on its own page"
                  className="rounded-md border border-line px-2 py-0.5 text-[11px] text-accent hover:border-accent"
                >
                  open ↗
                </button>
              }
            >
              <Timeline events={task.timeline} status={task.status} />
            </Panel>
            <Panel title="Agent chat" meta={chatMeta(task)} className="h-[440px] flex-[2]" bodyClass="flex-1 overflow-auto p-3.5">
              <AgentChat events={task.stream} />
            </Panel>
          </div>
        )}

        <Playbook text={state?.playbook} />
      </div>
    </div>
  )
}
