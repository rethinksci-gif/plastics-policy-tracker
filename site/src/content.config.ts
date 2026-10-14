import { defineCollection } from 'astro:content';
import { glob } from 'astro/loaders';
import { z } from 'astro/zod';

// The Python pipeline validates every file with pydantic (the source of truth);
// these schemas only shape the data for the templates.
const fuzzyDate = z
  .union([z.string(), z.date()])
  .transform((v) => (v instanceof Date ? v.toISOString().slice(0, 10) : String(v)));

const update = z.object({
  date: fuzzyDate,
  summary: z.string(),
  source_url: z.string(),
  source_quote: z.string(),
  source_quote_en: z.string().nullish(),
  source_lang: z.string().default('en'),
  stage_change: z.string().nullish(),
  review_id: z.string(),
});

const dossiers = defineCollection({
  loader: glob({ base: '../dossiers', pattern: '*.yaml' }),
  schema: z.object({
    id: z.string(),
    title: z.string(),
    short_title: z.string().nullish(),
    title_original: z.string().nullish(),
    jurisdiction: z.string(),
    instrument: z.string(),
    topics: z.array(z.string()),
    stage: z.string(),
    affected: z.array(z.string()),
    impact: z.enum(['high', 'medium', 'low']),
    official_links: z.array(z.string()),
    summary: z.string().nullish(),
    updates: z.array(update).default([]),
    next_steps: z
      .array(z.object({ date: fuzzyDate, text: z.string(), source_url: z.string(), status: z.string().default('expected') }))
      .default([]),
    key_dates: z.array(z.object({ date: fuzzyDate, text: z.string(), source_url: z.string().nullish() })).default([]),
  }),
});

const issueSchema = z.object({
  title: z.string(),
  number: z.number(),
  date: fuzzyDate,
  status: z.string(),
  highlights: z.array(z.string()).default([]),
  review_report: z.string(),
  items_count: z.number().default(0),
  quarantined_count: z.number().default(0),
  description: z.string().default(''),
});

const issues = defineCollection({
  loader: glob({ base: '../issues', pattern: '*.md' }),
  schema: issueSchema,
});

// Draft issues (dry runs, or issues held by the publish gate) are only built when SHOW_DRAFTS=1.
const drafts = defineCollection({
  loader: glob({ base: '../data/drafts', pattern: process.env.SHOW_DRAFTS === '1' ? '*.md' : '__none__' }),
  schema: issueSchema,
});

const reviews = defineCollection({
  loader: glob({ base: '../reviews/items', pattern: '*.json' }),
  schema: z.object({
    review_id: z.string(),
    candidate_id: z.string(),
    dossier_id: z.string(),
    created: z.string(),
    impact: z.string(),
    outcome: z.string(),
    reasons: z.array(z.string()).default([]),
    checks: z.array(z.object({ layer: z.number(), name: z.string(), passed: z.boolean(), severity: z.string(), detail: z.string() })),
    llm_review: z
      .object({ verdict: z.string(), confidence: z.number(), checks: z.record(z.string(), z.boolean()), issues: z.array(z.string()) })
      .nullish(),
  }),
});

const issueReviews = defineCollection({
  loader: glob({ base: '../reviews/issues', pattern: '*.json' }),
  schema: z.object({
    review_id: z.string(),
    issue: z.string(),
    created: z.string(),
    decision: z.string(),
    would_publish: z.boolean(),
    hold_reasons: z.array(z.string()).default([]),
    quarantine_ratio: z.number(),
    published_items: z.array(z.object({ id: z.string(), dossier: z.string(), review_id: z.string(), summary: z.string() })),
    quarantined_items: z.array(
      z.object({ id: z.string(), dossier: z.string(), title: z.string(), impact: z.string(), summary: z.string().nullish(), source_url: z.string(), reasons: z.array(z.string()) }),
    ),
    editorial_review: z.record(z.string(), z.any()),
  }),
});

export const collections = { dossiers, issues, drafts, reviews, issueReviews };
