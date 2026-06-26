// Pure formatting helpers + the role model, shared by the components.

export const fmtK = (n) => {
  if (!n) return '0'
  return n >= 1000 ? (n / 1000).toFixed(n >= 10000 ? 0 : 1) + 'k' : '' + n
}

export const shortModel = (m) => (m ? m.replace(/^claude-/, '').replace(/-\d{8}$/, '') : '')

export function evMeta(ev) {
  const b = []
  if (ev.model) b.push(shortModel(ev.model))
  if (ev.in_tok != null || ev.out_tok != null) b.push(fmtK(ev.in_tok) + '→' + fmtK(ev.out_tok) + ' tok')
  if (ev.cost) b.push('$' + ev.cost.toFixed(4))
  if (ev.dur != null) b.push('⏱ ' + ev.dur + 's')
  return b.join(' · ')
}

// The four collaborating roles. `color` maps to a Tailwind palette key.
export const ROLES = [
  { k: 'spec', n: 'Spec-writer', color: 'purple', desc: 'writes the spec & locks the acceptance tests' },
  { k: 'eng', n: 'Engineer', color: 'accent', desc: 'implements until the gate (tests) passes' },
  { k: 'rev', n: 'Reviewer', color: 'good', desc: 'reviews the diff, approves or requests changes' },
  { k: 'lead', n: 'Tech-lead', color: 'amber', desc: 'updates the playbook so the next task is smarter' },
]

// Derive each role's status for one task from its timeline. null => the role hasn't acted.
export function loopStatus(tl) {
  const s = { spec: null, eng: null, rev: null, lead: null }
  if (!tl) return s
  let n = 0,
    gate = null,
    lastBad = false,
    rev = null,
    merged = false
  for (const e of tl) {
    if (e.event === 'spec') s.spec = (e.tests ? e.tests.length : 0) + ' test(s) locked'
    else if (e.event === 'attempt') {
      n++
      gate = e.gate_passed
      lastBad = false // a fresh attempt clears the prior verdict
    } else if (e.event === 'tamper' || e.event === 'isolation') lastBad = true
    else if (e.event === 'review') rev = e
    else if (e.event === 'merged') merged = !!e.merged
    else if (e.event === 'playbook') s.lead = 'playbook refreshed'
  }
  if (n) {
    const o = merged ? 'gate ✓' : lastBad ? '⚠ gaming rejected' : gate ? 'gate ✓' : 'gate ✗'
    s.eng = n + ' attempt' + (n > 1 ? 's' : '') + ' · ' + o
  }
  if (rev) s.rev = rev.score + '/100 · ' + (rev.approved ? 'approved' : 'changes requested')
  return s
}

// Literal class maps (Tailwind scans these strings, so they get compiled in).
export const BADGE = {
  merged: 'bg-good/10 text-good',
  failed: 'bg-bad/10 text-bad',
  "spec'd": 'bg-amber/10 text-amber',
}
export const BAR = { merged: 'bg-good', failed: 'bg-bad', "spec'd": 'bg-amber' }
export const ROLE_BORDER = { purple: 'border-purple', accent: 'border-accent', good: 'border-good', amber: 'border-amber' }
export const ROLE_TEXT = { purple: 'text-purple', accent: 'text-accent', good: 'text-good', amber: 'text-amber' }
