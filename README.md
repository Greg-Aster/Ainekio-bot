# Ainekio the Robot Familiar

  Ainekio the Robot Familiar is a hardware and software project for building a small robot companion powered by MetaHuman OS. The robot uses a physical body,
  onboard sensors, and a network connection to let MetaHuman OS see, listen, speak, move, and interact through a physical chassis.

- Progress blog and current status: [ainek.io](https://ainek.io)
- MetaHuman OS development repo: [Greg-Aster/metahuman-os](https://github.com/Greg-Aster/metahuman-os)
- Current test body: based on the Sesame robot: [dorianborian/sesame-robot](https://github.com/dorianborian/sesame-robot)

## Website

The public website is `https://ainek.io`.

Website source does not live in this robot repo. It lives in the Merkin monorepo so it can stay on the same shared Temporal Flow site architecture as the other Merkin sites:

- source app: `apps/ainekio` in the Merkin monorepo
- local workspace path: `/home/greggles/Merkin/apps/ainekio`
- shared site architecture: `packages/blog-core` in the Merkin monorepo
- Cloudflare Pages project: `merkin-ainekio`
- Merkin deploy command: `pnpm deploy:ainekio`

This repo remains focused on the Ainekio robot project: hardware, firmware, local robot code, safety notes, and project documentation.

## Domain

`ainek.io` should be connected through Cloudflare Pages, not GitHub Pages. In Cloudflare, add `ainek.io` as a custom domain on the `merkin-ainekio` Pages project after the domain is active in the Cloudflare zone. Cloudflare Pages should create or verify the needed DNS record for the apex domain.
