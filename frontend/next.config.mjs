/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    // Resolve internal or public backend URL
    const rawHost =
      process.env.BACKEND_INTERNAL_HOST ||
      process.env.NEXT_PUBLIC_API_URL ||
      'http://localhost:8000';

    let target = rawHost.trim();
    if (!target.startsWith('http://') && !target.startsWith('https://')) {
      // If it's an internal Render host like 'paypact-backend', it listens on port 10000
      const port = target.includes(':') ? '' : ':10000';
      target = `http://${target}${port}`;
    }
    target = target.replace(/\/api\/?$/, '').replace(/\/+$/, '');

    return [
      {
        source: '/api/:path*',
        destination: `${target}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
