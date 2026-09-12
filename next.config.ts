import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emit .next/standalone with a minimal server.js and only the node_modules
  // actually reached at runtime. This is what lets the web image ship without
  // installing dependencies at all — see web.Dockerfile.
  //
  // `public/` and `.next/static` are NOT copied into standalone automatically;
  // the Dockerfile copies them in, or the portraits and stylesheets 404.
  //
  // Skipped on Vercel, which sets VERCEL=1 during its build. Vercel is a
  // verified Next.js adapter and produces its own output; standalone is a
  // self-hosting format and only makes that build do extra work.
  output: process.env.VERCEL ? undefined : "standalone",
};

export default nextConfig;
