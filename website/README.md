# Kumpas website

Static marketing site: `index.html`, `style.css`, `script.js`, icons, and
`og-image.png` (the preview picture shown when the link is shared). No build step.

Preview locally:

    python3 -m http.server -d website 8000    # then open http://localhost:8000

## Hosting

GitHub Pages publishes this folder at https://maxspeedy27.github.io/phoneremote/ whenever `website/` changes on
`main` (`.github/workflows/pages.yml`; also runnable by hand from the Actions tab).
`og-image.html` and this README are not published.

- **Own domain later:** add it under the repository's Settings → Pages, then
  replace `https://maxspeedy27.github.io/phoneremote/` in `index.html` (the canonical link and the `og:url` /
  `og:image` tags: social sites need the absolute `og:image` URL).
- **Price:** the page doesn't mention one. Add it to the hero and download
  section once decided.

## Social image

`og-image.png` is rendered from `og-image.html` (instructions at its top).
