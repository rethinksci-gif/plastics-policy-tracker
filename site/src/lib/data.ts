import { getCollection, type CollectionEntry } from 'astro:content';

export const SITE_NAME = 'Plastics Policy Tracker';

export const STAGES = [
  'planned', 'consultation', 'impact-assessment', 'proposal', 'parliament-council', 'trilogue',
  'adopted', 'published', 'in-force', 'implementing-acts', 'in-application',
];

const STAGE_LABELS: Record<string, string> = {
  'parliament-council': 'Parliament & Council',
  trilogue: 'trilogue / negotiation',
  'impact-assessment': 'impact assessment',
  'implementing-acts': 'implementing acts',
  'in-force': 'in force',
  'in-application': 'in application',
};
export const stageLabel = (s: string) => STAGE_LABELS[s] ?? s;

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

// ---------------------------------------------------------------------------
// Laws & policies library
// ---------------------------------------------------------------------------

export const INSTRUMENTS: Record<string, string> = {
  regulation: 'Regulation', directive: 'Directive', 'implementing-act': 'Implementing act', 'delegated-act': 'Delegated act',
  decision: 'Decision', 'national-law': 'National law', standard: 'Standard', treaty: 'Treaty', tax: 'Tax',
  'EPR-scheme': 'EPR scheme', policy: 'Policy',
};
export const instrumentName = (i: string) => INSTRUMENTS[i] ?? i;

export const ROOT_NAMES: Record<string, string> = {
  GLOBAL: 'Global', EU: 'EU and Member States', UK: 'United Kingdom', US: 'United States', CN: 'China',
};
export const jurRoot = (c: string) => c.split('-')[0];

const daysBetween = (a: string, b: string) => (Date.parse(b) - Date.parse(a)) / 864e5;

/** review_id -> slug of the published issue that carried it. */
export async function issueOfReview(): Promise<Map<string, string>> {
  const out = new Map<string, string>();
  const published = new Set((await getCollection('issues')).map((i) => i.id));
  for (const r of await getCollection('issueReviews')) {
    if (r.data.decision !== 'publish' || !published.has(r.data.issue)) continue;
    for (const p of r.data.published_items) out.set(p.review_id, r.data.issue);
  }
  return out;
}

export interface LibraryEntry {
  d: Dossier;
  summary: string | null;          // shown only when its review passed for exactly this text
  summaryStatus: 'verified' | 'pending' | 'failed' | 'none';
  summaryReviewId: string | null;
  lastChange: string | null;       // date of the newest verified update
  changedRecently: boolean;        // newest update within 30 days
  nextDate: CalEvent | null;       // next upcoming key date / next step
}

export async function library(): Promise<LibraryEntry[]> {
  const reviews = new Map((await getCollection('summaryReviews')).map((r) => [r.data.dossier_id, r.data]));
  const today = todayIso();
  const events = (await calendarEvents()).filter((e) => e.end >= today);
  return (await dossiers()).map((d) => {
    const r = reviews.get(d.id);
    let summaryStatus: LibraryEntry['summaryStatus'] = 'none';
    if (d.summary) {
      if (!r || r.summary.trim() !== d.summary.trim()) summaryStatus = 'pending';
      else summaryStatus = r.outcome === 'passed' ? 'verified' : 'failed';
    }
    const last = d.updates[0]?.date ?? null;
    return {
      d,
      summary: summaryStatus === 'verified' ? d.summary! : null,
      summaryStatus,
      summaryReviewId: r && summaryStatus !== 'pending' ? r.review_id : null,
      lastChange: last,
      changedRecently: !!last && daysBetween(dateEnd(last), today) <= 30,
      nextDate: events.find((e) => e.dossier === d.id) ?? null,
    };
  });
}

export interface ChangeEntry { d: Dossier; u: Dossier['updates'][number]; issue: string | null }

export async function allChanges(): Promise<ChangeEntry[]> {
  const issueMap = await issueOfReview();
  return (await dossiers())
    .flatMap((d) => d.updates.map((u) => ({ d, u, issue: issueMap.get(u.review_id) ?? null })))
    .sort((a, b) => b.u.date.localeCompare(a.u.date) || a.d.title.localeCompare(b.d.title));
}
