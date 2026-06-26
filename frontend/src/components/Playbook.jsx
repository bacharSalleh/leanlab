import Panel from './Panel'

export default function Playbook({ text }) {
  return (
    <Panel
      title="Playbook"
      hint="the project's growing conventions, written by the tech-lead"
      bodyClass="max-h-[300px] overflow-auto p-3.5"
    >
      <pre className="m-0 whitespace-pre-wrap font-mono text-[12.5px] text-muted">
        {text || 'No playbook yet — it grows as tasks merge.'}
      </pre>
    </Panel>
  )
}
