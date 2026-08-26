# The Next.js frontend.
#
# Multi-stage, ending on `output: "standalone"` (see next.config.ts): the final
# image carries a minimal server.js and only the node_modules actually reached
# at runtime, so nothing is installed in the runner at all.

# ── deps ────────────────────────────────────────────────────────────────────
FROM node:22-alpine AS deps
WORKDIR /app
# Only the manifests, so a source edit does not re-run the install.
COPY package.json package-lock.json ./
RUN npm ci

# ── build ───────────────────────────────────────────────────────────────────
FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY package.json package-lock.json next.config.ts tsconfig.json postcss.config.mjs ./
COPY app ./app
COPY public ./public

ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# ── runner ──────────────────────────────────────────────────────────────────
FROM node:22-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN addgroup --system --gid 1001 nodejs \
 && adduser --system --uid 1001 nextjs

COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
# standalone does NOT include these two, and without them the portraits and
# stylesheets 404 while the pages themselves still render — a failure that is
# easy to miss. Verified locally by running server.js with both copied in.
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

USER nextjs
EXPOSE 3000

# HOSTNAME=0.0.0.0 above is required: the default binds the container's own
# loopback, which nothing outside it can reach.
CMD ["node", "server.js"]

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD node -e "require('http').get('http://127.0.0.1:3000/',r=>process.exit(r.statusCode===200?0:1)).on('error',()=>process.exit(1))"
