exports.handler = async function(event, context) {
  return {
    statusCode: 200,
    headers: {
      'Content-Type': 'application/javascript',
      'Cache-Control': 'no-cache, no-store, must-revalidate'
    },
    body: `window.WF_GROQ_API_KEY = '${process.env.GROQ_API_KEY || ''}';`
  };
};