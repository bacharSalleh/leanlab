import { useEffect, useState } from 'react'

// One SSE connection. Re-opens when the selected task changes. The server emits
// `state` (always) and `task` (when a task is in the query) events.
export function useStream(selected) {
  const [state, setState] = useState(null)
  const [task, setTask] = useState(null)
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    setTask(null) // don't show the previous task while the new one loads
    const url = '/api/stream' + (selected ? '?task=' + encodeURIComponent(selected) : '')
    const es = new EventSource(url)
    es.addEventListener('open', () => setConnected(true))
    es.addEventListener('error', () => setConnected(false))
    es.addEventListener('state', (e) => setState(JSON.parse(e.data)))
    es.addEventListener('task', (e) => setTask(JSON.parse(e.data)))
    return () => es.close()
  }, [selected])

  return { state, task, connected }
}
