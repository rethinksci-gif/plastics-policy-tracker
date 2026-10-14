import type { APIContext } from 'astro';
import { calendarEvents, dossiers } from '../../../lib/data';
import { buildIcs } from '../../../lib/ics';

export async function getStaticPaths() {
  return (await dossiers()).map((d) => ({ params: { id: d.id }, props: { id: d.id, name: d.short_title ?? d.title } }));
}

export async function GET({ props, site }: APIContext) {
  const { id, name } = props as { id: string; name: string };
  const base = new URL(import.meta.env.BASE_URL, site).toString().replace(/\/$/, '');
  return buildIcs((await calendarEvents()).filter((e) => e.dossier === id), base, `${name} · Plastics Policy Tracker`);
}
