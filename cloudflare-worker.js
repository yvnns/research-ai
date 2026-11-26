// Cloudflare Worker: proxy for blocked search/image providers.
// Deploy via Cloudflare Dashboard (Workers) and set SEARCH_PROXY_URL in Render to this worker URL.
export default {
  async fetch(request) {
    const url = new URL(request.url);
    const target = url.searchParams.get("url");
    if (!target) {
      return new Response("missing url", { status: 400 });
    }
    try {
      const res = await fetch(target, {
        headers: { "User-Agent": "Mozilla/5.0 (compatible; ResearchAI/1.0)" },
      });
      const body = await res.arrayBuffer();
      const headers = new Headers(res.headers);
      headers.set("Access-Control-Allow-Origin", "*");
      return new Response(body, { status: res.status, headers });
    } catch (e) {
      return new Response(String(e), { status: 502 });
    }
  },
};
