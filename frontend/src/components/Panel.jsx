// Card wrapper: a titled, bordered panel with a flexible body.
export default function Panel({ title, hint, meta, right, className = '', bodyClass = '', children }) {
  return (
    <section className={'flex min-w-0 flex-col rounded-xl border border-line bg-panel ' + className}>
      <div className="flex items-center gap-2 border-b border-line px-3.5 py-2.5 text-xs font-semibold">
        <span>{title}</span>
        {hint && <span className="font-normal text-muted">{hint}</span>}
        {(meta || right) && (
          <span className="ml-auto flex items-center gap-2 font-normal">
            {meta && <span className="text-muted">{meta}</span>}
            {right}
          </span>
        )}
      </div>
      <div className={'min-h-0 ' + bodyClass}>{children}</div>
    </section>
  )
}
