// F18: Lighthouse CI 配置 — 性能门禁
//
// 配置流式收集 + 本地断言门禁。
// 方案 system-diagnosis-and-optimization-plan.md F18 要求设定 Performance > 60 最低线。
// Performance 设为 error（硬门禁），其余类别为 warn（渐进式改善）。
// 参考: docs/system-diagnosis-and-optimization-plan.md §5.4 F18
//
// 用法:
//   lhci autorun --config=.lighthouserc.js
//   lhci healthcheck --config=.lighthouserc.js

module.exports = {
  ci: {
    collect: {
      // 从生产构建的 serve 收集
      url: [
        "http://localhost:3000/",
        "http://localhost:3000/dashboard",
      ],
      numberOfRuns: 2,
      settings: {
        preset: "desktop",
      },
    },
    assert: {
      // F18: Performance 硬门禁 >= 60（最低线）；其余类别渐进式 warn
      assertions: {
        "categories:performance": ["error", { minScore: 0.6 }],
        "categories:accessibility": ["warn", { minScore: 0.8 }],
        "categories:best-practices": ["warn", { minScore: 0.8 }],
        "categories:seo": ["warn", { minScore: 0.8 }],
        // 核心 Web Vitals 基线
        "largest-contentful-paint": ["warn", { maxNumericValue: 8000 }],
        "total-blocking-time": ["warn", { maxNumericValue: 500 }],
        // F13: CLS 目标 < 0.1（配合 .main min-height 预留空间）
        "cumulative-layout-shift": ["error", { maxNumericValue: 0.1 }],
      },
    },
    upload: {
      target: "temporary-public-storage",
    },
  },
};
