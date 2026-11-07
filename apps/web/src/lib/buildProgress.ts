// C4: the engine stops when the schedule stops improving (≈8 s without a better one, or proven within 1% of the
// best possible), with a 90 s safety cap. The web only words what the engine reports.

export const BUILD_CAP_S = 90
/** After this the line says the build is still improving. */
export const STILL_IMPROVING_AFTER_S = 10

export function progressMessage(elapsedS: number): string {
  const s = Math.floor(Math.max(0, elapsedS))
  return elapsedS < STILL_IMPROVING_AFTER_S
    ? `Building your week… ${s} s`
    : `Still improving — stops when the schedule stops getting better (max ${BUILD_CAP_S} s) · ${s} s`
}

const STOP_REASON: Record<string, string> = {
  proven_close: 'Best schedule found (within 1% of the best possible)',
  plateau: 'Stopped when it stopped improving',
  cap: `Stopped at the ${BUILD_CAP_S} s limit`,
}

/** `solver_stats.stop_reason` in plain words, plus the seconds taken; null when there's nothing to say. */
export function stopReasonLine(stats: Record<string, unknown> | null | undefined): string | null {
  const why = STOP_REASON[String(stats?.stop_reason ?? '')]
  if (!why) return null
  const s = typeof stats?.total_s === 'number' ? stats.total_s : null
  return s != null ? `${why} · ${Math.round(s)} s` : why
}
