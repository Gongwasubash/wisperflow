const fs = require('fs');
const path = require('path');

const isNetlify = process.env.NETLIFY === 'true';
let apiKey = '';

if (isNetlify) {
  apiKey = process.env.GROQ_API_KEY || '';
  console.log('Running on Netlify, using env var');
} else {
  const envPath = path.join(__dirname, '..', '.env');
  if (fs.existsSync(envPath)) {
    const content = fs.readFileSync(envPath, 'utf8');
    const match = content.match(/GROQ_API_KEY=(.+)/);
    if (match) {
      apiKey = match[1].trim();
      console.log('Running locally, using .env file');
    }
  }
}

console.log('API Key present:', !!apiKey);

const jsContent = `window.WF_GROQ_API_KEY = '${apiKey}';\n`;
fs.writeFileSync('api-key.js', jsContent);