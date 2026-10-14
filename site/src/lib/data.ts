import { getCollection, type CollectionEntry } from 'astro:content';

export const SITE_NAME = 'Plastics Policy Tracker';

export const STAGES = [
  'planned', 'consultation', 'impact-assessment', 'proposal', 'parliament-council', 'trilogue',
  'adopted', 'published', 'in-force', 'implementing-acts', 'in-application',
];

export const JURISDICTIONS: Record<string, string> = {
  GLOBAL: 'Global', EU: 'European Union', UK: 'United Kingdom', US: 'United States', CN: 'China',
  'EU-FR': 'France', 'EU-NL': 'Netherlands', 'EU-DE': 'Germany', 'EU-IT': 'Italy', 'EU-ES': 'Spain', 'EU-SE': 'Sweden',
  'US-FED': 'US federal', 'US-CA': 'California', 'US-OR': 'Oregon', 'US-CO': 'Colorado', 'US-ME': 'Maine',
  'US-MN': 'Minnesota', 'US-MD': 'Maryland', 'US-WA': 'Washington State',
};
export const jurName = (c: string) => JURISDICTIONS[c] ?? c;

const ROOT_ORDER = ['GLOBAL', 'EU', 'UK', 'US', 'CN'];
export function jurSortKey(c: string): string {
  const root = c.split('-')[0];
  const i = ROOT_ORDER.indexOf(root);
  return `${i < 0 ? 9 : i}${c === root ? 0 : 1}${c}`;
}

export const url = (path = '') => `${import.meta.env.BASE_URL.replace(/\/$/, '')}/${path.replace(/^\//, '')}`;

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
export function fmtDate(d: string): string {
  const [y, m, day] = d.split('-');
  return day ? `${Number(day)} ${MONTHS[Number(m) - 1]} ${y}` : `${MONTHS[Number(m) - 1]} ${y}`;
}

/** Last calendar day a fuzzy date (YYYY-MM or YYYY-MM-DD) can refer to. */
export function dateEnd(d: string): string {
  const [y, m, day] = d.split('-').map(Number);
  if (day) return d;
  return new Date(Date.UTC(y, m, 0)).toISOString().slice(0, 10);
}

export const todayIso = () => new Date().toISOString().slice(0, 10);

export type Dossier = CollectionEntry<'dossiers'>['data'];

export async function dossiers(): Promise<Dossier[]> {
  const all = (await getCollection('dossiers')).map((e) => e.data);
  return all.sort((a, b) => jurSortKey(a.jurisdiction).localeCompare(jurSortKey(b.jurisdiction)) || a.title.localeCompare(b.title));
}

export async function issues() {
  const pub = await getCollection('issues');
  const drafts = await getCollection('drafts');
  return [...pub, ...drafts.map((d) => ({ ...d, collection: 'drafts' as const }))].sort((a, b) =>
    b.data.date.localeCompare(a.data.date) || b.data.number - a.data.number,
  );
}

export interface CalEvent { date: string; end: string; dossier: string; title: string; text: string; kind: string; source_url?: string | null }

export async function calendarEvents(): Promise<CalEvent[]> {
  const out: CalEvent[] = [];
  for (const d of await dossiers()) {
    const t = d.short_title ?? d.title;
    for (const k of d.key_dates) out.push({ date: k.date, end: dateEnd(k.date), dossier: d.id, title: t, text: k.text, kind: 'key date', source_url: k.source_url });
    for (const n of d.next_steps)
      out.push({ date: n.date, end: dateEnd(n.date), dossier: d.id, title: t, text: n.text, kind: n.status === 'to-be-confirmed' ? 'to be confirmed' : 'expected', source_url: n.source_url });
  }
  return out.sort((a, b) => a.date.localeCompare(b.date));
}
