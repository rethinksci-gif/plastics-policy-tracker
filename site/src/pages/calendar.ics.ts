import type { APIRoute } from 'astro';
import { calendarEvents } from '../lib/data';
import { buildIcs } from '../lib/ics';

export const GET: APIRoute = async ({ site }) => {
  const base = new URL(import.meta.env.BASE_URL, site).toString().replace(/\/$/, '');
  return buildIcs(await calendarEvents(), base, 'Plastics Policy Tracker');
};
