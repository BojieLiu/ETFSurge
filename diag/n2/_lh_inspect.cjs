const lh = require('lighthouse');
console.log('typeof lh:', typeof lh);
console.log('keys:', Object.keys(lh).slice(0, 20));
console.log('lh.lighthouse:', typeof lh.lighthouse);
console.log('lh.default:', typeof lh.default);