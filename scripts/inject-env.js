const fs = require('fs');

const apiKey = process.env.GROQ_API_KEY || '';

const jsContent = `window.WF_GROQ_API_KEY = '${apiKey}';\n`;

fs.writeFileSync('api-key.js', jsContent);

console.log('API key injected into api-key.js');