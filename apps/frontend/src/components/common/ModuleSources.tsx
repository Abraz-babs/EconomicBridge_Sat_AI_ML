/**
 * "Fed by" — the satellites and datasets behind a module, named under its
 * title so a reader always knows what is measured, by whom, and what each
 * source contributes. Every module header carries one (operator's standing
 * rule, 2026-09-26). Name only what the module actually reads today; a source
 * that is planned but not wired belongs in the module's own "coming" note,
 * never here.
 */

export interface ModuleSource {
  /** The satellite, instrument or publisher, e.g. "Copernicus Sentinel-2". */
  name: string;
  /** What it contributes here, e.g. "vegetation greenness, every LGA". */
  role: string;
}

export default function ModuleSources({ sources }: { sources: ModuleSource[] }) {
  return (
    <div className="module-sources" aria-label="Data sources for this module">
      <span className="module-sources-label">Fed by</span>
      {sources.map((s, i) => (
        <span key={s.name} className="module-source">
          <strong>{s.name}</strong> {s.role}
          {i < sources.length - 1 ? <span aria-hidden="true" className="module-source-sep">·</span> : null}
        </span>
      ))}
    </div>
  );
}
