// @ts-check
import { defineConfig } from 'astro/config';

export default defineConfig({
  site: 'https://rethinksci-gif.github.io',
  base: '/plastics-policy-tracker',
  trailingSlash: 'ignore',
  build: { format: 'directory' },
});
