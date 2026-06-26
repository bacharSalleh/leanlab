// Loop-faithful timeline. The coding loop is deterministic:
//   spec → ( engineer → gate → review )* → merge → tech-lead
// Each round is one engineer→gate→review iteration; the loop-back between rounds is shown
// explicitly. Spec / outcome / tech-lead frame the loop. Missing stages read "no record".

function GateLine({ a }) {
  const ok = a.gate_passed
  return (
    <div>
      <span className={ok ? 'text-good' : 'text-bad'}>{ok ? '✓ gate passed' : '✗ gate failed'}</span>
      {!ok && a.failures?.length ? <span className="text-muted"> · {a.failures.join(', ')}</span> : null}
    </div>
  )
}

function Stage({ label, color, done, children }) {
  return (
    <div className={done ? '' : 'opacity-40'}>
      <div className={'text-[13px] font-semibold ' + color}>{label}</div>
      <div className="mt-0.5 pl-3 text-xs">{done ? children : <span className="italic text-muted">no record</span>}</div>
    </div>
  )
}

export default function Timeline({ events, status }) {
  const evs = events || []
  const specs = evs.filter((e) => e.event === 'spec')
  const merged = evs.find((e) => e.event === 'merged')
  const gaveup = evs.find((e) => e.event === 'gaveup')
  const playbook = evs.find((e) => e.event === 'playbook')

  // Fold the event stream into rounds: each 'attempt' opens a round; gate flags + the review
  // for that round attach to it (chronological order, so re-runs stay in sequence).
  const rounds = []
  for (const e of evs) {
    if (e.event === 'attempt') rounds.push({ a: e, flags: [], review: null })
    else if ((e.event === 'tamper' || e.event === 'isolation') && rounds.length) rounds[rounds.length - 1].flags.push(e)
    else if (e.event === 'review' && rounds.length) rounds[rounds.length - 1].review = e
  }

  const isMerged = status === 'merged' || !!merged
  const partial = isMerged && (!specs.length || !evs.some((e) => e.event === 'review'))

  return (
    <div className="space-y-3">
      {partial && (
        <div className="rounded-md border border-amber/40 bg-amber/10 px-3 py-2 text-[11.5px] text-amber">
          ⚠ partial record — this task is merged but its spec/review events weren't logged (an older run).
        </div>
      )}

      <Stage label="Spec-writer" color="text-purple" done={specs.length > 0}>
        {specs.map((s, i) => (
          <div key={i} className="text-muted">
            locked {s.tests ? s.tests.length : 0} acceptance test(s)
          </div>
        ))}
      </Stage>

      <div className={rounds.length ? '' : 'opacity-40'}>
        <div className="text-[13px] font-semibold text-accent">
          Engineer ⇄ Reviewer loop
          {rounds.length ? ` · ${rounds.length} round${rounds.length > 1 ? 's' : ''}` : ''}
        </div>
        {rounds.length === 0 ? (
          <div className="mt-0.5 pl-3 text-xs italic text-muted">no record</div>
        ) : (
          <ol className="mt-1 space-y-1">
            {rounds.map((r, i) => (
              <li key={i} className="rounded-md border border-line bg-panel2/40 px-3 py-2 text-xs">
                <div className="font-semibold text-ink">Round {i + 1} · attempt {r.a.n}</div>
                <div className="mt-0.5 space-y-0.5 pl-2">
                  <GateLine a={r.a} />
                  {r.flags.map((f, j) => (
                    <div key={j} className="text-bad">
                      ⚠ {f.event === 'tamper'
                        ? 'modified the locked tests — rejected'
                        : 'passed only with its own fixtures — rejected'}
                    </div>
                  ))}
                  {r.review && (
                    <div>
                      <span className="text-good">Reviewer</span>{' '}
                      <span className={r.review.approved ? 'text-good' : 'text-bad'}>
                        {r.review.score}/100 {r.review.approved ? '✓ approved' : '✗ changes requested'}
                      </span>
                      {r.review.feedback ? <span className="text-muted"> · {r.review.feedback}</span> : null}
                    </div>
                  )}
                </div>
                {i < rounds.length - 1 && <div className="mt-1 text-[11px] text-amber">↻ loop back — fix &amp; retry</div>}
              </li>
            ))}
          </ol>
        )}
      </div>

      <Stage label="Outcome" color={merged ? 'text-good' : gaveup ? 'text-bad' : 'text-ink'} done={!!merged || !!gaveup}>
        {merged ? (
          <span className="text-good">✓ merged → main</span>
        ) : gaveup ? (
          <span className="text-bad">✗ gave up after {gaveup.attempts} attempt(s) — not merged</span>
        ) : null}
      </Stage>

      <Stage label="Tech-lead" color="text-amber" done={!!playbook}>
        <span className="text-muted">refreshed the playbook</span>
      </Stage>
    </div>
  )
}
