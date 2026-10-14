import rss from '@astrojs/rss';
import type { APIContext } from 'astro';
import { getCollection } from 'astro:content';
import { SITE_NAME } from '../lib/data';

export async function GET(context: APIContext) {
  const issues = (await getCollection('issues')).sort((a, b) => b.data.date.localeCompare(a.data.date));
  const base = import.meta.env.BASE_URL.replace(/\/$/, '');
  return rss({
    title: SITE_NAME,
    description: 'Biweekly, source-verified updates on plastics laws and regulations worldwide.',
    site: context.site!,
    items: issues.map((i) => ({
      title: i.data.title,
      pubDate: new Date(i.data.date + 'T06:00:00Z'),
      description: [i.data.description, ...i.data.highlights.map((h) => `• ${h}`)].join('\n'),
      link: `${base}/issues/${i.id}/`,
    })),
    customData: '<language>en-gb</language>',
  });
}
