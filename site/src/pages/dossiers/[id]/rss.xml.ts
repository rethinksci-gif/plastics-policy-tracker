import rss from '@astrojs/rss';
import type { APIContext } from 'astro';
import { SITE_NAME, dossiers, issueOfReview } from '../../../lib/data';

export async function getStaticPaths() {
  return (await dossiers()).map((d) => ({ params: { id: d.id }, props: { d } }));
}

export async function GET(context: APIContext) {
  const { d } = context.props as { d: Awaited<ReturnType<typeof dossiers>>[number] };
  const base = import.meta.env.BASE_URL.replace(/\/$/, '');
  const issues = await issueOfReview();
  return rss({
    title: `${d.short_title ?? d.title} · ${SITE_NAME}`,
    description: `Verified changes to ${d.title}.`,
    site: context.site!,
    items: d.updates.map((u) => ({
      title: `${d.short_title ?? d.title}: ${u.summary.slice(0, 110)}${u.summary.length > 110 ? '…' : ''}`,
      pubDate: new Date((u.date.length === 7 ? `${u.date}-01` : u.date) + 'T00:00:00Z'),
      description: `${u.summary}\n\nSource: ${u.source_url}${issues.get(u.review_id) ? `\nReported in ${issues.get(u.review_id)}` : ''}`,
      link: `${base}/dossiers/${d.id}/#change-${u.review_id}`,
    })),
    customData: '<language>en-gb</language>',
  });
}
