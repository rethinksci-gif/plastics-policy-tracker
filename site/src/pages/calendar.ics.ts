import type { APIRoute } from 'astro';
import { calendarEvents } from '../lib/data';

const esc = (s: string) => s.replace(/\\/g, '\\\\').replace(/;/g, '\;').replace(/,/g, '\\,').replace(/\n/g, '\\n');
const compact = (d: string) => d.replace(/-/g, '');
function nextDay(iso: string) { const d = new Date(iso + 'T00:00:00Z'); d.setUTCDate(d.getUTCDate() + 1); return d.toISOString().slice(0, 10); }
function fold(line: string) {
  const out: string[] = [];
  let s = line;
  while (s.length > 74) { out.push(s.slice(0, 74)); s = ' ' + s.slice(74); }
  out.push(s);
  return out.join('\r\n');
}

export const GET: APIRoute = async ({ site }) => {
  const base = new URL(import.meta.env.BASE_URL, site).toString().replace(/\/$/, '');
  const stamp = new Date().toISOString().replace(/[-:]/g, '').slice(0, 15) + 'Z';
  const lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Plastics Policy Tracker//EN', 'CALSCALE:GREGORIAN',
    'X-WR-CALNAME:Plastics Policy Tracker', 'X-WR-TIMEZONE:UTC'];
  for (const e of await calendarEvents()) {
    const start = e.date.length === 7 ? `${e.date}-01` : e.date;
    const uid = `${e.dossier}-${compact(e.date)}-${Buffer.from(e.text).toString('base64url').slice(0, 16)}@plastics-policy-tracker`;
    lines.push('BEGIN:VEVENT', `UID:${uid}`, `DTSTAMP:${stamp}`, `DTSTART;VALUE=DATE:${compact(start)}`,
      `DTEND;VALUE=DATE:${compact(nextDay(e.end))}`,
      fold(`SUMMARY:${esc(`${e.title}: ${e.text}${e.kind === 'key date' ? '' : ` (${e.kind})`}`)}`),
      fold(`URL:${base}/dossiers/${e.dossier}/`),
      fold(`DESCRIPTION:${esc(`${e.text}\nSource: ${e.source_url ?? 'see dossier'}\n${base}/dossiers/${e.dossier}/`)}`),
      'END:VEVENT');
  }
  lines.push('END:VCALENDAR');
  return new Response(lines.join('\r\n') + '\r\n', { headers: { 'Content-Type': 'text/calendar; charset=utf-8' } });
};
