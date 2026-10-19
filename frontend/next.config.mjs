/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    // Resolve public or local backend URL for API proxying
    const rawHost =
      process.env.NEXT_PUBLIC_API_URL ||
      process.env.BACKEND_URL ||
      process.env.BACKEND_INTERNAL_HOST ||
      'http://localhost:8000';

    let target = (rawHost || '').trim();
    if (!target) {
      target = 'http://localhost:8000';
    }

    if (!target.startsWith('http://') && !target.startsWith('https://')) {
      if (
        target === 'localhost' ||
        target === '127.0.0.1' ||
        target.startsWith('localhost:') ||
        target.startsWith('127.0.0.1:')
      ) {
        target = `http://${target.includes(':') ? target : `${target}:8000`}`;
      } else if (!target.includes('.')) {
        // On Render free plan, internal hostnames (like 'paypact-backend') cannot receive
        // private traffic. Route through Render's public HTTPS domain instead.
        target = `https://${target}.onrender.com`;
      } else {
        target = `https://${target}`;
      }
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
