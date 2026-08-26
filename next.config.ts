import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emit .next/standalone with a minimal server.js and only the node_modules
  // actually reached at runtime. This is what lets the web image ship without
  // installing dependencies at all — see web.Dockerfile.
  //
  // `public/` and `.next/static` are NOT copied into standalone automatically;
  // the Dockerfile copies them in, or the portraits and stylesheets 404.
  output: "standalone",
};

export default nextConfig;
