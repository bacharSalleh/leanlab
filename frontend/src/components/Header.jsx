export default function Header({ lab, sub, connected, full }) {
  return (
    <header className="sticky top-0 z-10 flex items-center gap-2.5 border-b border-line bg-panel px-5 py-3">
      <span aria-hidden>🛠</span>
      <b className="text-[15px]">{lab || 'leanlab'}</b>
      <span className="text-xs text-muted">{sub || 'coding board'}</span>
      <span className="flex-1" />
      {full && (
        <a href="/" className="mr-3 text-xs text-muted hover:text-ink">
          ← board
        </a>
      )}
      <span className="text-xs text-muted">{connected ? '● streaming' : '○ reconnecting…'}</span>
    </header>
  )
}
