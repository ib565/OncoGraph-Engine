/** @type {import('next').NextConfig} */
const nextConfig = {
  // Improve chunk loading for dynamic imports
  webpack: (config, { isServer }) => {
    if (!isServer) {
      config.resolve.fallback = {
        ...config.resolve.fallback,
        fs: false,
        net: false,
        tls: false,
      };
    }
    return config;
  },
  // Optimize chunks for better loading
  experimental: {
    optimizeCss: true,
  },
  // Ensure proper chunk loading
  generateEtags: false,
  poweredByHeader: false,
};

module.exports = nextConfig;

