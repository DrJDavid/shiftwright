import { BuildProgressLine } from './BuildProgressLine'

/** Overlay shown while a solve runs. No time estimate: the engine stops when the schedule stops improving (C4). */
export function SolveProgress({ startedAt, coveragePct }: { startedAt: number; coveragePct?: number | null }) {
  return (
    <div className="absolute inset-0 z-30 flex items-start justify-center bg-panel/70 pt-24 backdrop-blur-[1px]">
      <div className="w-[26rem] rounded-lg border border-rule bg-panel p-5 shadow-lg">
        <h3 className="font-semibold">Building the week</h3>
        <div className="mt-1">
          <BuildProgressLine startedAt={startedAt} coveragePct={coveragePct} />
        </div>
        <div className="sw-progress relative mt-3 h-1.5 overflow-hidden rounded-full bg-pine-wash" aria-hidden />
        <p className="mt-2 text-xs text-muted">A separate compliance check reviews it before you see it.</p>
      </div>
    </div>
  )
}
