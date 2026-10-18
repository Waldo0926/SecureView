/**
 * Every time the site shows a person, in one zone: Kuala Lumpur (UTC+8, no daylight saving).
 *
 * The server stores and sends UTC; only what is put on screen changes. Formatting in the
 * browser's own zone made one page read 05:30 while the security agent beside it said 21:30
 * UTC for the same moment, so nothing on screen uses the browser's zone any more, and every
 * time carries its zone label. The server-side counterpart is `app/core/time.py`
 * (`site_stamp`), which writes the security agent's evidence lines in the same form.
 */
export const SITE_TIME_ZONE = 'Asia/Kuala_Lumpur'
export const SITE_TIME_ZONE_LABEL = 'MYT'
/** Malaysia has kept +08:00 all year since 1982, so a fixed offset is exact. */
const SITE_OFFSET_MS = 8 * 60 * 60 * 1000

const parts = new Intl.DateTimeFormat('en-CA', {
  timeZone: SITE_TIME_ZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hourCycle: 'h23',
})

function toDate(value: string | number | Date): Date {
  return value instanceof Date ? value : new Date(value)
}

function pieces(date: Date): Record<string, string> {
  const out: Record<string, string> = {}
  for (const part of parts.formatToParts(date)) out[part.type] = part.value
  return out
}

/** `2026-10-13 02:19:05 MYT`, or the input unchanged when it is not a time. */
export function formatSiteDateTime(
  value: string | number | Date,
  options: { seconds?: boolean } = {},
): string {
  const date = toDate(value)
  if (Number.isNaN(date.getTime())) return String(value)
  const p = pieces(date)
  const time = options.seconds === false ? `${p.hour}:${p.minute}` : `${p.hour}:${p.minute}:${p.second}`
  return `${p.year}-${p.month}-${p.day} ${time} ${SITE_TIME_ZONE_LABEL}`
}

/** `2026-10-13`, the calendar day in Kuala Lumpur. */
export function formatSiteDate(value: string | number | Date): string {
  const date = toDate(value)
  if (Number.isNaN(date.getTime())) return String(value)
  const p = pieces(date)
  return `${p.year}-${p.month}-${p.day}`
}

/** The first or last instant of a Kuala Lumpur calendar day, as a UTC ISO string. */
export function siteDayBoundary(year: number, month: number, day: number, edge: 'start' | 'end'): string {
  const utc =
    edge === 'start'
      ? Date.UTC(year, month - 1, day, 0, 0, 0, 0)
      : Date.UTC(year, month - 1, day, 23, 59, 59, 999)
  return new Date(utc - SITE_OFFSET_MS).toISOString()
}
