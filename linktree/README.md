# PokerPilot link-in-bio page

Built from [LinkTreeFreeClone](https://github.com/yoanbernabeu/LinkTreeFreeClone) (MIT, see `LICENSE`).

* Buttons: one Markdown file per button in `src/data/links/` (`order`, `title`, `emoji`, `href`, optional `primary: true`).
* Text: `src/config.ts`. Icons under the logo: `src/data/socials/`.
* Avatar: `public/avatar.png`.

Build: `npm ci && npm run build`, which outputs the static site to `dist/`.
