/** @type {import('next').NextConfig} */
module.exports = {
  output: "standalone",
  // Proxy browser API calls through the dashboard origin so auth cookies are
  // first-party and no CORS is involved. Server components still hit the API
  // directly via lib/api.ts.
  async rewrites() {
    const api =
      process.env.API_INTERNAL_URL ||
      process.env.NEXT_PUBLIC_API_URL ||
      "http://localhost:8080";
    return [{ source: "/api/:path*", destination: `${api}/api/:path*` }];
  },
};
