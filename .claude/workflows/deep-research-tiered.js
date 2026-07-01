export const meta = {
  name: "deep-research-tiered",
  description:
    "Deep research with model tiering — Haiku does the wide search/fetch/verify fan-out, Opus handles scope decomposition and synthesis. Final ADR/KB consolidation stays in the main session (research loop).",
  whenToUse:
    "Gather stage of the research loop (docs/research/<slug>/). Same pipeline as built-in deep-research but ~10x cheaper on the fan-out. Pass the refined research question as args.",
  phases: [
    {
      title: "Scope",
      detail: "Decompose question (from args) into 5 search angles",
      model: "opus",
    },
    {
      title: "Search",
      detail: "5 parallel WebSearch agents, one per angle",
      model: "haiku",
    },
    {
      title: "Fetch",
      detail: "URL-dedup, fetch top 15 sources, extract falsifiable claims",
      model: "haiku",
    },
    {
      title: "Verify",
      detail:
        "3-vote adversarial verification per claim (need 2/3 refutes to kill)",
      model: "haiku",
    },
    {
      title: "Synthesize",
      detail: "Merge semantic dupes, rank by confidence, cite sources",
      model: "opus",
    },
  ],
};

// Tiered variant of the built-in deep-research workflow.
// Model pyramid: Haiku on the wide mechanical fan-out (search/fetch/verify — ~95% of
// agent calls), Opus on the two judgment-heavy single calls (scope, synthesize).
// Verify stays on Haiku because the 3-vote majority + refuted-by-default prompt
// compensate for lower per-voter capability; upgrade to 'sonnet' if good claims
// get killed too aggressively. ADR/KB consolidation is NOT done here — it runs in
// the main session via refine-research + process-research (needs repo context).
// Question is passed via Workflow({name: 'deep-research-tiered', args: '<question>'}).
//
// ─── Resilience contract (P1 — dogfood visto-saas 2026-06-27) ───
// This gather is expensive (millions of subagent tokens) and is run unattended, so a
// single dead agent must NEVER discard the whole run. Three guarantees:
//   1. NO bare agent() call can throw the workflow away. agent() can REJECT (not just
//      resolve null) on a terminal error — e.g. "StructuredOutput retry cap (5) exceeded".
//      Inside parallel()/pipeline() the framework already turns a throw into null, but a
//      top-level `await agent()` (scope, synthesize) would propagate and kill everything.
//      safeAgent() catches the throw → null, so the existing null-guards take over.
//   2. Scope is the single point of failure (no angles → nothing to search). It retries
//      once, then falls back to heuristic angles — the run degrades, it does not die.
//   3. Partial results are returned BY DEFAULT. The whole gather body runs under a
//      try/catch; any unanticipated throw salvages whatever was already produced
//      (verified claims > raw claims > sources) instead of losing it. Every exit path
//      reports reliability + cost so a degraded run is never mistaken for "nothing found".

const VOTES_PER_CLAIM = 3;
const REFUTATIONS_REQUIRED = 2;
const MAX_FETCH = 15;
const MAX_VERIFY_CLAIMS = 25;
const SCOPE_RETRIES = 1; // extra attempts after the first, before heuristic fallback

// ─── Schemas ───
const SCOPE_SCHEMA = {
  type: "object",
  required: ["question", "angles", "summary"],
  properties: {
    question: { type: "string" },
    summary: { type: "string" },
    angles: {
      type: "array",
      minItems: 3,
      maxItems: 6,
      items: {
        type: "object",
        required: ["label", "query"],
        properties: {
          label: { type: "string" },
          query: { type: "string" },
          rationale: { type: "string" },
        },
      },
    },
  },
};
const SEARCH_SCHEMA = {
  type: "object",
  required: ["results"],
  properties: {
    results: {
      type: "array",
      maxItems: 6,
      items: {
        type: "object",
        required: ["url", "title", "relevance"],
        properties: {
          url: { type: "string" },
          title: { type: "string" },
          snippet: { type: "string" },
          relevance: { enum: ["high", "medium", "low"] },
        },
      },
    },
  },
};
const EXTRACT_SCHEMA = {
  type: "object",
  required: ["claims", "sourceQuality"],
  properties: {
    sourceQuality: {
      enum: ["primary", "secondary", "blog", "forum", "unreliable"],
    },
    publishDate: { type: "string" },
    claims: {
      type: "array",
      maxItems: 5,
      items: {
        type: "object",
        required: ["claim", "quote", "importance"],
        properties: {
          claim: { type: "string" },
          quote: { type: "string" },
          importance: { enum: ["central", "supporting", "tangential"] },
        },
      },
    },
  },
};
const VERDICT_SCHEMA = {
  type: "object",
  required: ["refuted", "evidence", "confidence"],
  properties: {
    refuted: { type: "boolean" },
    evidence: { type: "string" },
    confidence: { enum: ["high", "medium", "low"] },
    counterSource: { type: "string" },
  },
};
const REPORT_SCHEMA = {
  type: "object",
  required: ["summary", "findings", "caveats"],
  properties: {
    summary: { type: "string" },
    findings: {
      type: "array",
      items: {
        type: "object",
        required: ["claim", "confidence", "sources", "evidence"],
        properties: {
          claim: { type: "string" },
          confidence: { enum: ["high", "medium", "low"] },
          sources: { type: "array", items: { type: "string" } },
          evidence: { type: "string" },
          vote: { type: "string" },
        },
      },
    },
    caveats: { type: "string" },
    openQuestions: { type: "array", items: { type: "string" } },
  },
};

// ─── safeAgent: agent() that degrades a THROW to null (Guarantee 1) ───
// parallel()/pipeline() already null-ify a throwing agent; this gives the SAME contract
// to top-level awaits (scope, synthesize) so a terminal StructuredOutput/API error can
// never unwind the whole workflow. The log line names which agent died and why — the
// observability the dogfood run was missing.
async function safeAgent(prompt, opts) {
  try {
    return await agent(prompt, opts);
  } catch (e) {
    log(
      "agent '" +
        (opts && opts.label ? opts.label : "?") +
        "' threw (" +
        (e && e.message ? e.message : String(e)) +
        ") — degrading to null",
    );
    return null;
  }
}

// ─── Cost/observability — surfaced on EVERY exit path, not just the happy one ───
function cost(parts) {
  const tokensSpent =
    typeof budget !== "undefined" &&
    budget &&
    typeof budget.spent === "function"
      ? budget.spent()
      : null;
  return { ...parts, tokensSpent };
}

// ─── Heuristic fallback angles — keeps the gather alive if scope can't be decomposed ───
// Generic but non-degenerate: primary / implementation / criticism / recency / tradeoffs.
// A run that uses these is flagged degraded (scopeDegraded) so the caller knows coverage
// was not tailored to the question.
function fallbackScope(question) {
  return {
    question,
    summary:
      "Heuristic fallback decomposition (scope agent unavailable) — generic angles, coverage not tailored.",
    angles: [
      {
        label: "primary/authoritative",
        query: question,
        rationale: "Authoritative or primary sources on the core question",
      },
      {
        label: "technical/implementation",
        query: question + " implementation details how it works",
        rationale: "Practitioner / technical depth",
      },
      {
        label: "limitations/criticism",
        query: question + " limitations problems criticism risks",
        rationale: "Contrarian / skeptical angle",
      },
      {
        label: "recent/state-of-art",
        query: question + " latest 2026 state of the art",
        rationale: "Recency",
      },
      {
        label: "alternatives/tradeoffs",
        query: question + " alternatives comparison tradeoffs",
        rationale: "Comparison and tradeoffs",
      },
    ],
  };
}

// ─── Phase 0: Scope (opus) — angle decomposition shapes all downstream coverage ───
phase("Scope");
const QUESTION = (typeof args === "string" && args.trim()) || "";
if (!QUESTION) {
  return {
    error:
      "No research question provided. Pass it as args: Workflow({name: 'deep-research-tiered', args: '<question>'}).",
  };
}
const SCOPE_PROMPT =
  "Decompose this research question into complementary search angles.\n\n" +
  "## Question\n" +
  QUESTION +
  "\n\n" +
  "## Task\n" +
  "Generate 5 distinct web search queries that together cover the question from different angles. Pick angles that suit the question's domain. Examples:\n" +
  "- broad/primary  · academic/technical  · recent news  · contrarian/skeptical  · practitioner/implementation\n" +
  "- For medical: anatomy · common causes · serious differentials · authoritative refs · red flags\n" +
  "- For tech: state-of-art · benchmarks · limitations · industry adoption · cost/tradeoffs\n\n" +
  "Make queries specific enough to surface high-signal results. Avoid redundancy.\n" +
  "Return: the question (verbatim or lightly normalized), a 1-2 sentence decomposition strategy, and the angles.\n\nStructured output only.";

// Retry once (scope is a single point of failure), then heuristic fallback (Guarantee 2).
let scope = null;
let scopeDegraded = false;
for (let attempt = 0; attempt <= SCOPE_RETRIES && !scope; attempt++) {
  scope = await safeAgent(SCOPE_PROMPT, {
    label: attempt === 0 ? "scope" : "scope-retry-" + attempt,
    schema: SCOPE_SCHEMA,
    model: "opus",
  });
  if (!scope && attempt < SCOPE_RETRIES) {
    log("scope agent returned no result — retrying (" + (attempt + 1) + ")");
  }
}
if (!scope) {
  log(
    "scope agent failed " +
      (SCOPE_RETRIES + 1) +
      "x — using heuristic fallback angles (DEGRADED coverage)",
  );
  scope = fallbackScope(QUESTION);
  scopeDegraded = true;
}
log("Q: " + QUESTION.slice(0, 80) + (QUESTION.length > 80 ? "…" : ""));
log(
  "Decomposed into " +
    scope.angles.length +
    " angles: " +
    scope.angles.map((a) => a.label).join(", ") +
    (scopeDegraded ? " (fallback)" : ""),
);

// ─── Dedup state — accumulates across searchers as they complete ───
const normURL = (u) => {
  try {
    const p = new URL(u);
    return (
      p.hostname.replace(/^www\./, "") + p.pathname.replace(/\/$/, "")
    ).toLowerCase();
  } catch {
    return u.toLowerCase();
  }
};
const seen = new Map();
const dupes = [];
const budgetDropped = [];
const relRank = { high: 0, medium: 1, low: 2 };
let fetchSlots = MAX_FETCH;

// ─── Prompts ───
const SEARCH_PROMPT = (angle) =>
  "## Web Searcher: " +
  angle.label +
  "\n\n" +
  'Research question: "' +
  QUESTION +
  '"\n\n' +
  "Your angle: **" +
  angle.label +
  "** — " +
  (angle.rationale || "") +
  "\n" +
  "Search query: `" +
  angle.query +
  "`\n\n" +
  "## Task\nUse WebSearch with the query above (or a refined version). Return the top 4-6 most relevant results.\n" +
  "Rank by relevance to the ORIGINAL question, not just the search query. Skip obvious SEO spam/content farms.\n" +
  "Include a short snippet capturing why each result is relevant.\n\nStructured output only.";

const FETCH_PROMPT = (source, angle) =>
  "## Source Extractor\n\n" +
  'Research question: "' +
  QUESTION +
  '"\n\n' +
  "Fetch and extract key claims from this source:\n" +
  "**URL:** " +
  source.url +
  "\n**Title:** " +
  source.title +
  "\n**Found via:** " +
  angle +
  " search\n\n" +
  "## Task\n1. Use WebFetch to retrieve the page content.\n" +
  "2. Assess source quality: primary research/institution? secondary reporting? blog/opinion? forum? unreliable?\n" +
  "3. Extract 2-5 FALSIFIABLE claims that bear on the research question. Each claim must:\n" +
  "   - be a concrete, checkable statement (not vague generalities)\n" +
  "   - include a direct quote from the source as support\n" +
  "   - be rated central/supporting/tangential to the research question\n" +
  "4. Note publish date if available.\n\n" +
  'If the fetch fails or the page is irrelevant/paywalled, return claims: [] and sourceQuality: "unreliable".\n\nStructured output only.';

const VERIFY_PROMPT = (claim, v) =>
  "## Adversarial Claim Verifier (voter " +
  (v + 1) +
  "/" +
  VOTES_PER_CLAIM +
  ")\n\n" +
  "Be SKEPTICAL. Try to REFUTE this claim. ≥" +
  REFUTATIONS_REQUIRED +
  "/" +
  VOTES_PER_CLAIM +
  " refutations kill it.\n\n" +
  "## Research question\n" +
  QUESTION +
  "\n\n" +
  '## Claim under review\n"' +
  claim.claim +
  '"\n\n' +
  "**Source:** " +
  claim.sourceUrl +
  " (" +
  claim.sourceQuality +
  ")\n" +
  '**Supporting quote:** "' +
  claim.quote +
  '"\n\n' +
  "## Checklist\n" +
  "1. Is the claim actually supported by the quote, or is it an overreach/misread?\n" +
  "2. WebSearch for contradicting evidence — does any credible source dispute or heavily qualify this?\n" +
  "3. Is the source quality sufficient for the claim's strength? (extraordinary claims need primary sources)\n" +
  "4. Is the claim outdated? (check dates — old claims about fast-moving fields are suspect)\n" +
  "5. Is this a marketing claim / press release / cherry-picked benchmark / forum speculation?\n\n" +
  "**refuted=true** if: unsupported by quote / contradicted / low-quality source for strong claim / outdated / marketing fluff.\n" +
  "**refuted=false** ONLY if: claim is well-supported, current, and source quality matches claim strength.\n" +
  "Default to refuted=true if uncertain.\n\nStructured output only. Evidence MUST be specific.";

// ─── Accumulators in outer scope so the partial-salvage catch can read them (Guarantee 3) ───
let searchResults = [];
let allSources = [];
let allClaims = [];
let rankedClaims = [];
let voted = [];
let confirmed = [];
let killed = [];

// Build a degraded/partial result from whatever state currently exists. Preference order:
// verified-confirmed claims > all verified > raw extracted claims > sources. Always honest:
// never fabricates findings, always reports reliability + cost.
function salvage(reason, extra) {
  const base = {
    question: QUESTION,
    partial: true,
    degraded: true,
    summary: reason,
    findings: [],
    confirmed: confirmed.map((c) => ({
      claim: c.claim,
      source: c.sourceUrl,
      quote: c.quote,
      vote: c.verdicts.length - c.refutedVotes + "-" + c.refutedVotes,
    })),
    refuted: killed.map((c) => ({
      claim: c.claim,
      vote: c.verdicts.length - c.refutedVotes + "-" + c.refutedVotes,
      source: c.sourceUrl,
    })),
    unverifiedClaims:
      confirmed.length === 0 && voted.length === 0
        ? allClaims.map((c) => ({
            claim: c.claim,
            source: c.sourceUrl,
            quality: c.sourceQuality,
          }))
        : [],
    sources: allSources.map((s) => ({
      url: s.url,
      quality: s.sourceQuality,
      claimCount: (s.claims || []).length,
    })),
    reliability: reliabilitySnapshot(),
    stats: cost({
      angles: scope.angles.length,
      sources: allSources.length,
      claims: allClaims.length,
      verified: voted.length,
      confirmed: confirmed.length,
      killed: killed.length,
    }),
  };
  return { ...base, ...(extra || {}) };
}

function reliabilitySnapshot() {
  const anglesLost = searchResults.filter((r) => r === null).length;
  const unreliableSources = allSources.filter(
    (s) => s.sourceQuality === "unreliable",
  ).length;
  // `degraded` = INFRASTRUCTURE failure (scope fell back, half the angles died, or every
  // source was unreliable) — NOT merely "0 findings". All-claims-refuted across healthy
  // sources is a legitimate research outcome, not a degraded run, so it must be excluded
  // here; otherwise the honest-refutation report below becomes unreachable.
  return {
    scopeDegraded,
    anglesPlanned: scope.angles.length,
    anglesLost,
    sources: allSources.length,
    unreliableSources,
    claimsVerified: voted.length,
    confirmed: confirmed.length,
    degraded:
      scopeDegraded ||
      anglesLost >= Math.ceil(scope.angles.length / 2) ||
      (allSources.length > 0 && unreliableSources === allSources.length),
  };
}

try {
  // ─── Pipeline: search → dedup → fetch+extract (no barrier) — all haiku ───
  searchResults = await pipeline(
    scope.angles,

    (angle) =>
      agent(SEARCH_PROMPT(angle), {
        label: "search:" + angle.label,
        phase: "Search",
        schema: SEARCH_SCHEMA,
        model: "haiku",
      }).then((r) => {
        if (!r) return null;
        log(angle.label + ": " + r.results.length + " results");
        return { angle: angle.label, results: r.results };
      }),

    (searchResult) => {
      const sorted = [...searchResult.results].sort(
        (a, b) => relRank[a.relevance] - relRank[b.relevance],
      );
      const novel = sorted.filter((r) => {
        const key = normURL(r.url);
        if (seen.has(key)) {
          dupes.push({ ...r, angle: searchResult.angle, dupOf: seen.get(key) });
          return false;
        }
        if (fetchSlots <= 0 && relRank[r.relevance] >= 1) {
          budgetDropped.push({ ...r, angle: searchResult.angle });
          return false;
        }
        seen.set(key, { angle: searchResult.angle, title: r.title });
        fetchSlots--;
        return true;
      });
      if (novel.length < searchResult.results.length) {
        log(
          searchResult.angle +
            ": " +
            novel.length +
            " novel (" +
            (searchResult.results.length - novel.length) +
            " filtered)",
        );
      }
      return parallel(
        novel.map((source) => () => {
          let host = "unknown";
          try {
            host = new URL(source.url).hostname.replace(/^www\./, "");
          } catch {}
          return agent(FETCH_PROMPT(source, searchResult.angle), {
            label: "fetch:" + host,
            phase: "Fetch",
            schema: EXTRACT_SCHEMA,
            model: "haiku",
          })
            .then((ext) => {
              // User-skip → null; drop it (filtered by searchResults.flat().filter(Boolean))
              // rather than throwing into .catch() and mislabeling it "unreliable".
              if (!ext) return null;
              return {
                url: source.url,
                title: source.title,
                angle: searchResult.angle,
                sourceQuality: ext.sourceQuality,
                publishDate: ext.publishDate,
                claims: ext.claims.map((c) => ({
                  ...c,
                  sourceUrl: source.url,
                  sourceQuality: ext.sourceQuality,
                })),
              };
            })
            .catch((e) => {
              log("fetch failed: " + source.url + " — " + (e.message || e));
              return {
                url: source.url,
                title: source.title,
                angle: searchResult.angle,
                sourceQuality: "unreliable",
                claims: [],
              };
            });
        }),
      );
    },
  );

  allSources = searchResults.flat().filter(Boolean);
  allClaims = allSources.flatMap((s) => s.claims);
  const impRank = { central: 0, supporting: 1, tangential: 2 };
  const qualRank = {
    primary: 0,
    secondary: 1,
    blog: 2,
    forum: 3,
    unreliable: 4,
  };

  rankedClaims = [...allClaims]
    .sort(
      (a, b) =>
        impRank[a.importance] - impRank[b.importance] ||
        qualRank[a.sourceQuality] - qualRank[b.sourceQuality],
    )
    .slice(0, MAX_VERIFY_CLAIMS);

  log(
    "Fetched " +
      allSources.length +
      " sources → " +
      allClaims.length +
      " claims → verifying top " +
      rankedClaims.length,
  );

  if (rankedClaims.length === 0) {
    // No claims to verify. If angles/scope degraded, say so loudly; either way return
    // sources + cost so the run is auditable (and never read as authoritative emptiness).
    return salvage(
      "No claims extracted — " +
        allSources.length +
        " sources fetched, all empty/failed/paywalled. " +
        dupes.length +
        " URL dupes, " +
        budgetDropped.length +
        " budget-dropped. Re-run the gather; do NOT consolidate.",
    );
  }

  // ─── Verify: 3-vote adversarial (haiku — majority vote compensates per-voter capability) ───
  // Barrier here is intentional — claim pool must be fully assembled before ranking/verification.
  phase("Verify");
  voted = (
    await parallel(
      rankedClaims.map(
        (claim) => () =>
          parallel(
            Array.from(
              { length: VOTES_PER_CLAIM },
              (_, v) => () =>
                agent(VERIFY_PROMPT(claim, v), {
                  label: "v" + v + ":" + claim.claim.slice(0, 40),
                  phase: "Verify",
                  schema: VERDICT_SCHEMA,
                  model: "haiku",
                }),
            ),
          ).then((verdicts) => {
            // A vote can be null (user-skip or agent error) — treat as abstain.
            const valid = verdicts.filter(Boolean);
            const refuted = valid.filter((v) => v.refuted).length;
            // Survive only if the claim was actually adjudicated: a quorum of
            // valid votes AND fewer than REFUTATIONS_REQUIRED refuting. Too many
            // abstentions = unverified, which must NOT pass into the report
            // (otherwise all-abstain → refuted=0 → false survive).
            const abstained = VOTES_PER_CLAIM - valid.length;
            const survives =
              valid.length >= REFUTATIONS_REQUIRED &&
              refuted < REFUTATIONS_REQUIRED;
            log(
              '"' +
                claim.claim.slice(0, 50) +
                '…": ' +
                (valid.length - refuted) +
                "-" +
                refuted +
                (abstained > 0 ? " (" + abstained + " abstain)" : "") +
                " " +
                (survives ? "✓" : "✗"),
            );
            return {
              ...claim,
              verdicts: valid,
              refutedVotes: refuted,
              survives,
            };
          }),
      ),
    )
  ).filter(Boolean);

  confirmed = voted.filter((c) => c.survives);
  killed = voted.filter((c) => !c.survives);

  const reliability = reliabilitySnapshot();
  log(
    "Verify done: " +
      voted.length +
      " claims → " +
      confirmed.length +
      " confirmed, " +
      killed.length +
      " killed",
  );

  // ─── Unified zero-confirmed exit (replaces the two old shadowed blocks) ───
  // The honest-vs-degraded distinction is the whole point of the dogfood complaint:
  // "all claims refuted by healthy verification" (a real finding) must read DIFFERENTLY
  // from "0 survived because half the agents died" (a broken run, do not consolidate).
  if (confirmed.length === 0) {
    const honestlyRefuted = !reliability.degraded && voted.length > 0;
    if (honestlyRefuted) {
      return {
        question: QUESTION,
        partial: false,
        degraded: false,
        summary:
          "All " +
          voted.length +
          " claims were refuted by 3-vote adversarial verification across healthy sources — research is genuinely inconclusive on this question (not a tooling failure).",
        findings: [],
        confirmed: [],
        refuted: killed.map((c) => ({
          claim: c.claim,
          vote: c.verdicts.length - c.refutedVotes + "-" + c.refutedVotes,
          source: c.sourceUrl,
        })),
        sources: allSources.map((s) => ({
          url: s.url,
          quality: s.sourceQuality,
          claimCount: s.claims.length,
        })),
        reliability,
        stats: cost({
          angles: scope.angles.length,
          sources: allSources.length,
          claims: allClaims.length,
          verified: voted.length,
          confirmed: 0,
          killed: killed.length,
        }),
      };
    }
    return salvage(
      "DEGRADED RUN — 0 claims survived verification (" +
        reliability.anglesLost +
        "/" +
        scope.angles.length +
        " angles lost" +
        (scopeDegraded ? ", scope used heuristic fallback" : "") +
        ", " +
        reliability.unreliableSources +
        " sources unreliable). This is NOT an authoritative 'nothing found' — re-run the gather; do NOT consolidate into an ADR/KB.",
    );
  }

  // ─── Synthesize (opus) — semantic merge + confidence ranking is judgment work ───
  phase("Synthesize");

  const confRank = { high: 0, medium: 1, low: 2 };
  const block = confirmed
    .map((c, i) => {
      const best = c.verdicts
        .filter((v) => !v.refuted)
        .sort((a, b) => confRank[a.confidence] - confRank[b.confidence])[0];
      return (
        "### [" +
        i +
        "] " +
        c.claim +
        "\n" +
        "Vote: " +
        (c.verdicts.length - c.refutedVotes) +
        "-" +
        c.refutedVotes +
        " · Source: " +
        c.sourceUrl +
        " (" +
        c.sourceQuality +
        ")\n" +
        'Quote: "' +
        c.quote +
        '"\nVerifier evidence (' +
        (best ? best.confidence : "n/a") +
        "): " +
        (best ? best.evidence : "—") +
        "\n"
      );
    })
    .join("\n");

  const killedBlock =
    killed.length > 0
      ? "\n## Refuted claims (for transparency)\n" +
        killed
          .map(
            (c) =>
              '- "' +
              c.claim +
              '" (' +
              c.sourceUrl +
              ", vote " +
              (c.verdicts.length - c.refutedVotes) +
              "-" +
              c.refutedVotes +
              ")",
          )
          .join("\n")
      : "";

  // safeAgent: a thrown synthesis (StructuredOutput cap) must reach the salvage path
  // below, NOT unwind the whole gather after all the expensive verify work is done.
  const report = await safeAgent(
    "## Synthesis: research report\n\n" +
      "**Question:** " +
      QUESTION +
      "\n\n" +
      confirmed.length +
      " claims survived " +
      VOTES_PER_CLAIM +
      "-vote adversarial verification. Merge semantic duplicates and synthesize.\n\n" +
      "## Confirmed claims\n" +
      block +
      "\n" +
      killedBlock +
      "\n\n" +
      "## Instructions\n" +
      "1. Identify claims that say the same thing — merge them, combine their sources.\n" +
      "2. Group related claims into coherent findings. Each finding should directly address the research question.\n" +
      "3. Assign confidence per finding: high (multiple primary sources, unanimous votes), medium (secondary sources or split votes), low (single source or blog-quality).\n" +
      "4. Write a 3-5 sentence executive summary answering the research question.\n" +
      "5. Note caveats: what's uncertain, what sources were weak, what time-sensitivity applies.\n" +
      "6. List 2-4 open questions that emerged but weren't answered.\n\nStructured output only.",
    { label: "synthesize", schema: REPORT_SCHEMA, model: "opus" },
  );

  // A returned-but-degenerate report (the model emitted a stub / no real findings / a trivial
  // summary) is as unusable as a null one — catch it instead of spreading garbage into the result.
  const degenerate =
    report &&
    (!Array.isArray(report.findings) ||
      report.findings.length === 0 ||
      typeof report.summary !== "string" ||
      report.summary.trim().length < 40);
  if (!report || degenerate) {
    // Synthesis skipped / errored / returned a stub — salvage the verified claims raw rather
    // than throwing on report.findings and discarding the whole run. This is NOT degraded
    // research (the claims passed verification) — only the merge step failed, so mark it
    // partial but keep the confirmed claims as the deliverable.
    return salvage(
      "Synthesis was skipped, failed, or returned a degenerate stub — salvaging " +
        confirmed.length +
        " verified claims unmerged (re-run if a clean synthesis is needed). The claims themselves passed 3-vote verification.",
      { degraded: false, afterSynthesis: 0 },
    );
  }

  return {
    question: QUESTION,
    partial: false,
    degraded: reliability.degraded,
    ...report,
    refuted: killed.map((c) => ({
      claim: c.claim,
      vote: c.verdicts.length - c.refutedVotes + "-" + c.refutedVotes,
      source: c.sourceUrl,
    })),
    sources: allSources.map((s) => ({
      url: s.url,
      quality: s.sourceQuality,
      angle: s.angle,
      claimCount: s.claims.length,
    })),
    reliability,
    stats: cost({
      angles: scope.angles.length,
      sourcesFetched: allSources.length,
      claimsExtracted: allClaims.length,
      claimsVerified: voted.length,
      confirmed: confirmed.length,
      killed: killed.length,
      afterSynthesis: report.findings.length,
      urlDupes: dupes.length,
      budgetDropped: budgetDropped.length,
      agentCalls:
        1 +
        scope.angles.length +
        allSources.length +
        voted.length * VOTES_PER_CLAIM +
        1,
    }),
  };
} catch (e) {
  // Guarantee 3: any unanticipated throw in the gather body salvages partial state
  // instead of discarding a multi-million-token run.
  log(
    "gather body threw (" +
      (e && e.message ? e.message : String(e)) +
      ") — salvaging partial state",
  );
  return salvage(
    "PARTIAL RUN — the gather threw mid-flight (" +
      (e && e.message ? e.message : String(e)) +
      "). Salvaged whatever was produced before the fault; treat as incomplete and re-run.",
  );
}
