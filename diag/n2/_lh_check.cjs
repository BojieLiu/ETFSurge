const lh = require('lighthouse');
console.log('lighthouse loaded:', typeof lh === 'function' ? 'fn' : typeof lh);
const { chromium } = require('playwright');
const { spawn } = require('child_process');