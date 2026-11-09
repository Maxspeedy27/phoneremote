# Phone Remote relay

Lets phones reach the laptop app from **any network with internet** (mobile
data, a different Wi-Fi, hotel or conference Wi-Fi that keeps devices apart),
and serves the phone page over real HTTPS, so there are no certificate warnings.

It's a Cloudflare Worker (serves the phone page) plus one Durable Object per
laptop (passes messages between that laptop and its phones). Messages stay
end-to-end encrypted with the keys from pairing; the relay doesn't parse them
and can't read or forge them. The one-time pairing key in the QR code's
`#fragment` never reaches it.

## Try it locally

```bash
cd relay
npm install
npm run dev                                   # http://127.0.0.1:8787
../.venv/bin/phoneremote --app --relay http://127.0.0.1:8787
```

The control panel then shows an **Any network** QR code. A phone can't open
`127.0.0.1` itself, so to test with a real phone deploy it (below), which
takes a minute and is free.

## Deploy

1. Create a free Cloudflare account.
2. `cd relay && npm install && npx wrangler login && npx wrangler deploy`.
   It prints the relay's address, e.g. `https://phoneremote-relay.<you>.workers.dev`.
   That already has HTTPS; a domain of your own is optional.
3. Put that address in `DEFAULT_RELAY_URL` in `src/phoneremote/relay.py` and
   build the installers again, so every copy of the app uses it. (To try it
   first: `phoneremote --app --relay https://...`.)
4. Optional: use your own domain (Cloudflare dashboard → Workers & Pages →
   phoneremote-relay → Settings → Domains & Routes).

`wrangler tail` shows live logs. Durable Objects with SQLite storage (used
here) are available on the free plan.

## Costs

The room uses Cloudflare's WebSocket hibernation: a laptop waiting for its
phone costs nothing, because keep-alive pings are answered without waking the
room. You pay for messages while someone uses the remote:

- Slides and touchpad: a few messages a second while touching the phone.
- Screen view: about 4–6 pictures and 10 pointer updates a second, roughly a
  cent per hour of viewing on the paid plan.

The free plan covers 100,000 Durable Object requests a day (WebSocket
messages count 20 to one request), plenty for testing and early users. The
Workers paid plan is US$5/month and includes far more. Cloudflare doesn't
charge for bandwidth, so screen pictures don't add data costs.

## Protocol

See the comments at the top of `src/worker.js` and
`src/phoneremote/relay.py`. In short: the laptop proves it owns its room by
sending the room secret whose SHA-256 gives the room id; phones send
`{"i", "p", "b"}` requests, which the relay prefixes with the phone's id for
the laptop, and the laptop's replies go back the same way.
