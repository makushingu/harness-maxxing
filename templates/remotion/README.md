# Remotion starter (shipped with Harness Maxxing)

Copied by the `video-motion-design` skill into a topic folder. The installer prepared Node.js and the
npm cache, so `npm install` is quick and offline-friendly; `remotion.config.js` renders with the server's
Chromium (the one Scrapling and PDFs use), so no second browser is downloaded.

    npm install --prefer-offline --no-audit --no-fund
    npm run still     # out/still.png - check a frame before rendering
    npm run render    # out/video.mp4
