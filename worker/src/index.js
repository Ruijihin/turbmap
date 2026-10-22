// 揺れやすさ地図の Cloudflare Worker。
//  - 画面(web/ フォルダ)は静的アセットとして自動で配信される
//  - /data/* は R2 バケットの中身を返す
//  - 定期実行(cron)で GitHub Actions のバッチを起動する

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname.startsWith("/data/")) {
      if (request.method !== "GET" && request.method !== "HEAD") {
        return new Response("Method Not Allowed", { status: 405 });
      }
      const key = decodeURIComponent(url.pathname.slice("/data/".length));
      if (!/^(index\.json|routes\/routes\.json|runs\/\d{10}\/(meta\.json|ft\d{2}\.png))$/.test(key)) {
        return new Response("Not Found", { status: 404 });
      }
      const obj = await env.BUCKET.get(key);
      if (!obj) return new Response("Not Found", { status: 404 });
      const headers = new Headers();
      obj.writeHttpMetadata(headers);
      headers.set("etag", obj.httpEtag);
      if (!headers.has("cache-control")) headers.set("cache-control", "no-cache");
      return new Response(request.method === "HEAD" ? null : obj.body, { headers });
    }
    // ここに来るのは静的アセットに無いパス
    return env.ASSETS.fetch(request);
  },

  async scheduled(event, env, ctx) {
    ctx.waitUntil(dispatch(env));
  },
};

async function dispatch(env) {
  const api = `https://api.github.com/repos/${env.GH_OWNER}/${env.GH_REPO}/actions/workflows/${env.GH_WORKFLOW}/dispatches`;
  const res = await fetch(api, {
    method: "POST",
    headers: {
      authorization: `Bearer ${env.GH_TOKEN}`,
      accept: "application/vnd.github+json",
      "x-github-api-version": "2022-11-28",
      "user-agent": "turbmap-worker",
    },
    body: JSON.stringify({ ref: env.GH_REF || "main", inputs: { init: "auto" } }),
  });
  if (res.status !== 204) {
    console.error("GitHub Actions を起動できませんでした", res.status, await res.text());
  }
}
