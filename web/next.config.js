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
    
    // Handle dynamic imports better
    config.module.rules.push({
      test: /\.m?js$/,
      type: "javascript/auto",
      resolve: {
        fullySpecified: false,
      },
    });
    
    return config;
  },
  // Optimize chunks for better loading
  experimental: {
    optimizeCss: true,
  },
  // Ensure proper chunk loading
  generateEtags: false,
  poweredByHeader: false,
  // Disable static optimization for pages with dynamic content
  trailingSlash: false,
  // Better handling of dynamic imports
  swcMinify: true,
};

module.exports = nextConfig;

