export default function handler(req) {
  return new Response(
    `window.WF_GROQ_API_KEY = '${process.env.GROQ_API_KEY}';`,
    {
      headers: { 'Content-Type': 'application/javascript' }
    }
  );
}