# PokerPilot link-in-bio page

Built from [LinkTreeFreeClone](https://github.com/yoanbernabeu/LinkTreeFreeClone) (MIT, see `LICENSE`).

* Buttons: one Markdown file per button in `src/data/links/` (`order`, `title`, `emoji`, `href`, optional `primary: true`).
* Text: `src/config.ts`. Icons under the logo: `src/data/socials/`.
* Avatar: `public/avatar.png`.

Build: `npm ci && npm run build`, which outputs the static site to `dist/`.

## Live site

Published on Netlify at **https://pokerpilot-club.netlify.app** (site id `bdf12898-e206-4711-9cde-b98d68ba7606`).
To update: build, zip the *contents* of `dist/`, and POST the zip to
`https://api.netlify.com/api/v1/sites/<site id>/deploys` with `Content-Type: application/zip`
(or drag `dist/` onto the site's Deploys page in the Netlify dashboard).
Visitor-access protection must stay off (`sso_login: false`) or visitors get a Netlify login page.
