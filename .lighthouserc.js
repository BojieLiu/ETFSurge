// F13: Lighthouse CI 配置 — 性能基线门禁
//
// 配置流式收集 + 本地断言门禁。
// 当前门禁设置为渐进式改善基线，随优化逐步收紧。
// 参考: docs/comprehensive-diagnosis-and-optimization-plan.md §11.4 F13
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
      // 渐进式门禁: Phase 1 基线 (Performance >= 50, 从29逐步提升)
      assertions: {
        "categories:performance": ["warn", { minScore: 0.5 }],
        "categories:accessibility": ["warn", { minScore: 0.8 }],
        "categories:best-practices": ["warn", { minScore: 0.8 }],
        "categories:seo": ["warn", { minScore: 0.8 }],
        // 核心 Web Vitals 基线
        "largest-contentful-paint": ["warn", { maxNumericValue: 8000 }],
        "total-blocking-time": ["warn", { maxNumericValue: 500 }],
        "cumulative-layout-shift": ["warn", { maxNumericValue: 0.1 }],
      },
    },
    upload: {
      target: "temporary-public-storage",
    },
  },
};
