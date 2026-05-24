// data.js — fake VRP history records for the rpkilog UI kit.
// Loaded as a plain global script (window.RpkilogData).

(function () {
  const TAS = ["arin", "ripe", "apnic", "lacnic", "afrinic"];
  const VERBS = ["REPLACE", "REPLACE", "REPLACE", "REPLACE", "INSERT", "DELETE", "EXPIRE"];

  // Deterministic pseudo-random so the demo is stable on reload.
  function lcg(seed) {
    let s = seed >>> 0;
    return () => {
      s = (s * 1664525 + 1013904223) >>> 0;
      return s / 0x100000000;
    };
  }

  function pad(n, w) { return String(n).padStart(w, "0"); }

  function toIso(d) {
    return (
      d.getUTCFullYear() + "-" +
      pad(d.getUTCMonth() + 1, 2) + "-" +
      pad(d.getUTCDate(), 2) + "T" +
      pad(d.getUTCHours(), 2) + ":" +
      pad(d.getUTCMinutes(), 2) + ":" +
      pad(d.getUTCSeconds(), 2) + "Z"
    );
  }

  function generate(prefix, asn, count) {
    const seed = (prefix + ":" + (asn || "")).split("").reduce((a, c) => a + c.charCodeAt(0), 0);
    const rnd = lcg(seed);
    const ta = TAS[Math.floor(rnd() * TAS.length)];
    const baseAsn = asn || 15169;
    const rows = [];
    let obsT = new Date("2026-05-24T14:14:07Z").getTime();
    for (let i = 0; i < count; i++) {
      const verb = VERBS[Math.floor(rnd() * VERBS.length)];
      const expA = new Date(obsT + 14 * 3600 * 1000 + Math.floor(rnd() * 16) * 3600 * 1000);
      const expB = new Date(expA.getTime() + (7 + Math.floor(rnd() * 16)) * 3600 * 1000);
      rows.push({
        prefix: prefix,
        maxLength: parseInt(prefix.split("/")[1], 10) || 24,
        asn: baseAsn,
        ta: ta,
        expires_old: toIso(expA),
        expires_new: toIso(expB),
        verb: verb,
        observation_timestamp: toIso(new Date(obsT)),
        expired: i % 3 !== 0,   // most "old" expiries shown as struck-through
      });
      // step back ~22h between observations
      obsT -= (22 * 3600 + Math.floor(rnd() * 3600)) * 1000;
    }
    return rows;
  }

  window.RpkilogData = {
    generate,
    search(query) {
      const prefix = (query.prefix || "").trim();
      const asn = query.asn ? parseInt(query.asn, 10) : null;
      if (!prefix && !asn) return { hits: 0, took: 0, shards: 162, rows: [] };
      const hits = prefix
        ? 1700 + (prefix.charCodeAt(0) % 200)
        : 80 + (asn % 400);
      const took = 80 + (hits % 240);
      const rows = generate(prefix || "0.0.0.0/0", asn, 50);
      return { hits, took, shards: 162, rows };
    },
  };
})();
