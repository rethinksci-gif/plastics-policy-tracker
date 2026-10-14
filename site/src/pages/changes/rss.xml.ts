import rss from '@astrojs/rss';
import type { APIContext } from 'astro';
import { SITE_NAME, allChanges } from '../../lib/data';

export async function GET(context: APIContext) {
  const base = import.meta.env.BASE_URL.replace(/\/$/, '');
  const changes = (await allChanges()).slice(0, 100);
  return rss({
    title: `${SITE_NAME} — all verified changes`,
    description: 'Every verified change to the tracked plastics laws and policies, as soon as it passes review.',
    site: context.site!,
    items: changes.map(({ d, u }) => ({
      title: `${d.short_title ?? d.title}: ${u.summary.slice(0, 110)}${u.summary.length > 110 ? '…' : ''}`,
      pubDate: new Date((u.date.length === 7 ? `${u.date}-01` : u.date) + 'T00:00:00Z'),
      description: `${u.summary}\n\nSource: ${u.source_url}`,
      link: `${base}/dossiers/${d.id}/#change-${u.review_id}`,
      categories: [d.jurisdiction, d.impact],
    })),
    customData: '<language>en-gb</language>',
  });
}
