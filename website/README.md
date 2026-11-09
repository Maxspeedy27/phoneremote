# Kumpas website

Static marketing site: `index.html`, `style.css`, `script.js`, icons, and
`og-image.png` (the preview picture shown when the link is shared). No build step.

Preview locally:

    python3 -m http.server -d website 8000    # then open http://localhost:8000

## Before going live

- **Domain:** `index.html` uses `https://getkumpas.com/` (available, not yet bought) as a placeholder in
  the canonical link and the `og:url` / `og:image` tags. Replace it with the
  real domain (social sites need the absolute `og:image` URL).
- **Download links** point at `github.com/Maxspeedy27/phoneremote/releases`.
  While that repository is private, visitors get a 404: make the repository
  (or a separate releases-only repository) public, or host the installers elsewhere.
- **Price:** the page doesn't mention one. Add it to the hero and download
  section once decided.

## Hosting

Any static host works. Cloudflare Pages fits, since the relay already runs on
Cloudflare: create a Pages project, point it at this repository, set the
build output directory to `website`, leave the build command empty.

## Social image

`og-image.png` is rendered from `og-image.html` (instructions at its top).
