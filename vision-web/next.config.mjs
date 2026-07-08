/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // App-wide defense: no crawling/indexing, ever (also enforced in middleware + robots.ts).
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Robots-Tag", value: "noindex, nofollow, noarchive, nosnippet, noimageindex" },
        ],
      },
    ];
  },
};

export default nextConfig;
