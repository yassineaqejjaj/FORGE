"use client";

import "./landing.css";

import Image from "next/image";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState, type CSSProperties, type MouseEvent } from "react";

const CTA_COLOR = "#d62e45";
const CONTACT_EMAIL = "yassine.aqejjaj@devoteam.com";
const DEMO_MAILTO = `mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent("Forge — demo request")}`;
const STAGGER = ["rv", "rv2", "rv3"] as const;

/** Scorecard of the hero — ProductAgent v1.4 on the Nordalis demo benchmark (illustrative). */
const METRICS = [
  { label: "Task success", value: "100%", pct: 100, color: "#5ab891" },
  { label: "Reasoning quality", value: "99%", pct: 99, color: "#4a8cca" },
  { label: "Policy compliance", value: "96%", pct: 96, color: "#5ab891" },
  { label: "Hallucination rate", value: "0%", pct: 2, color: "#fcc354" },
];

const WORDS = ["Framework", "Orchestrated", "Reasoning", "Governance", "Evaluation"];

const LETTERS = [
  { letter: "F", word: "Framework", text: "One shared method to define what “good” means for each agent, from use case to acceptance criteria." },
  { letter: "O", word: "Orchestrated", text: "Multi-agent flows and tool calls are traced end to end, so you test the whole chain, not one prompt." },
  { letter: "R", word: "Reasoning", text: "Every step of an agent’s reasoning is recorded and scored, so you see why it answered, not only what." },
  { letter: "G", word: "Governance", text: "Policies, guardrails and approvals live next to the tests, with an audit trail your risk team can read." },
  { letter: "E", word: "Evaluation", text: "Automated judges and human reviewers score each release against the same scenarios." },
];

const STEPS = [
  { num: "01", tag: "Define", title: "Set the bar", text: "Turn business rules and real conversations into scenarios, metrics and pass thresholds." },
  { num: "02", tag: "Evaluate", title: "Run the suite", text: "Forge replays every scenario on the new version and scores answers, tool calls and reasoning." },
  { num: "03", tag: "Govern", title: "Gate the release", text: "A release moves forward only when it clears your thresholds and the right people sign off." },
  { num: "04", tag: "Improve", title: "Fix what failed", text: "Failures become new scenarios. Production feedback flows back into the next run." },
];

const FEATURES = [
  { title: "Automated and human review", text: "LLM judges score at scale. Experts review the edge cases and calibrate the judges." },
  { title: "Release gates in CI/CD", text: "Block a deployment in GitHub Actions, GitLab or Azure DevOps when scores drop." },
  { title: "Guardrails and audit trail", text: "Every run, score and approval is logged and exportable for AI Act documentation." },
  { title: "Drift monitoring", text: "Sample live traffic and get alerted when quality moves away from your baseline." },
  { title: "Model-agnostic", text: "Compare GPT, Claude, Gemini, Mistral or your own models on the same scenarios." },
];

const AUDIENCES = [
  { who: "Product teams", text: "Ship new agent versions with evidence they are better, not a gut feeling." },
  { who: "Risk & compliance", text: "Review policies, test results and approvals in one place, release by release." },
  { who: "Platform engineering", text: "Add quality gates to the pipelines you already run, with no new stack to maintain." },
];

const HEADLINE: { word: string; delay: number; accent?: boolean }[] = [
  { word: "Know", delay: 200 },
  { word: "your", delay: 270 },
  { word: "AI", delay: 340 },
  { word: "agents", delay: 410 },
  { word: "work", delay: 520, accent: true },
  { word: "before", delay: 600 },
  { word: "your", delay: 670 },
  { word: "customers", delay: 740 },
  { word: "do.", delay: 810 },
];

const EYEBROW: CSSProperties = { fontSize: 13, fontWeight: 700, letterSpacing: "0.05em", textTransform: "uppercase" };
const SECTION_INNER: CSSProperties = { maxWidth: 1200, margin: "0 auto", display: "flex", flexDirection: "column", gap: 56 };
const SECTION_TITLE: CSSProperties = { margin: 0, fontSize: 44, lineHeight: 1.15, letterSpacing: "-0.02em", fontWeight: 300 };
const PILL: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  minHeight: 52,
  padding: "0 30px",
  borderRadius: 60,
  textDecoration: "none",
  fontSize: 16,
};
const NEON: CSSProperties = {
  position: "absolute",
  inset: 0,
  background: "#ff4d6b",
  boxShadow: "0 0 18px rgba(248,72,94,0.55), 0 0 44px rgba(248,72,94,0.25)",
};

function Arrow() {
  return (
    <svg className="arr" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M5 12h14" />
      <path d="m13 6 6 6-6 6" />
    </svg>
  );
}

interface Pointer {
  mx: number;
  my: number;
  rx: number;
  ry: number;
}

const REST: Pointer = { mx: 0.7, my: 0.35, rx: 0, ry: 0 };

/** Pointer-driven spotlight and card tilt (disabled for users who prefer reduced motion). */
function usePointerMotion() {
  const [pointer, setPointer] = useState<Pointer>(REST);
  const raf = useRef(0);
  const enabled = useRef(true);

  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    enabled.current = !query.matches;
    const onChange = (e: MediaQueryListEvent) => {
      enabled.current = !e.matches;
    };
    query.addEventListener("change", onChange);
    return () => {
      query.removeEventListener("change", onChange);
      if (raf.current) cancelAnimationFrame(raf.current);
    };
  }, []);

  const onMove = useCallback((e: MouseEvent<HTMLElement>) => {
    if (!enabled.current) return;
    const r = e.currentTarget.getBoundingClientRect();
    const nx = (e.clientX - r.left) / r.width;
    const ny = (e.clientY - r.top) / r.height;
    if (raf.current) cancelAnimationFrame(raf.current);
    raf.current = requestAnimationFrame(() => {
      setPointer({ mx: nx, my: ny, rx: (0.5 - ny) * 8, ry: (nx - 0.5) * 10 });
    });
  }, []);

  const onLeave = useCallback(() => setPointer(REST), []);
  return { pointer, onMove, onLeave };
}

export function LandingPage() {
  const { pointer, onMove, onLeave } = usePointerMotion();
  const marquee = [...WORDS, ...WORDS];

  return (
    <div
      id="top"
      className="forge-landing"
      style={{ width: "100%", fontFamily: "var(--font-landing), Montserrat, system-ui, sans-serif", color: "#3c3c3a", background: "#ffffff", fontWeight: 300 }}
    >
      {/* STICKY NAV (turns to glass on scroll) */}
      <header
        className="navbar"
        style={{ position: "sticky", top: 0, zIndex: 50, backgroundColor: "rgb(11,5,31)", borderBottom: "1px solid rgba(255,255,255,0)", backdropFilter: "blur(16px)", padding: "20px 24px" }}
      >
        <nav className="in" aria-label="Navigation principale" style={{ maxWidth: 1200, margin: "0 auto", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 24, flexWrap: "wrap" }}>
          <a href="#top" aria-label="Devoteam Forge, home" style={{ display: "flex", alignItems: "center" }}>
            <Image src="/landing/devoteam-forge-on-dark.png" alt="Devoteam | Forge" width={191} height={36} priority style={{ height: 36, width: "auto", display: "block" }} />
          </a>
          <div className="nav-links" style={{ display: "flex", alignItems: "center", gap: 32, flexWrap: "wrap", fontSize: 15, fontWeight: 500 }}>
            <a className="navlink nav-anchor" href="#framework">Framework</a>
            <a className="navlink nav-anchor" href="#how">How it works</a>
            <a className="navlink nav-anchor" href="#capabilities">Capabilities</a>
            <Link className="navlink" href="/login">Sign in</Link>
            <a className="btn" href="#contact" style={{ display: "inline-flex", alignItems: "center", minHeight: 44, padding: "0 22px", borderRadius: 60, border: "1px solid rgba(255,255,255,0.5)", textDecoration: "none", fontWeight: 600 }}>
              Book a demo
            </a>
          </div>
        </nav>
        <div className="progress" aria-hidden="true" style={{ position: "absolute", left: 0, right: 0, bottom: -1, height: 2, background: "#f8485e", transform: "scaleX(0)", boxShadow: "0 0 12px rgba(248,72,94,0.6)" }} />
      </header>

      <main>
        {/* HERO (dark) */}
        <section onMouseMove={onMove} onMouseLeave={onLeave} style={{ position: "relative", overflow: "hidden", background: "rgb(11,5,31)", color: "#ffffff", padding: "0 24px 128px" }}>
          <div
            aria-hidden="true"
            className="spot"
            style={{
              position: "absolute",
              left: 0,
              top: 0,
              width: 720,
              height: 720,
              margin: "-360px 0 0 -360px",
              borderRadius: "50%",
              pointerEvents: "none",
              background: "radial-gradient(circle, rgba(248,72,94,0.16) 0%, rgba(99,35,140,0.10) 35%, rgba(11,5,31,0) 70%)",
              transform: `translate(${pointer.mx * 100}vw, ${pointer.my * 900}px)`,
            }}
          />
          <div aria-hidden="true" className="trail" style={{ position: "absolute", left: "-10%", top: 330, width: "130%", height: 2, transform: "rotate(-9deg)" }}>
            <div className="breathe" style={NEON} />
            <div className="sweep" style={{ position: "absolute", left: 0, right: 0, top: -1, height: 4, borderRadius: 4 }} />
          </div>
          <div aria-hidden="true" className="trail" style={{ position: "absolute", left: "-10%", top: 356, width: "130%", height: 1, background: "#fca2ae", transform: "rotate(-9deg)", opacity: 0.35, animationDelay: "600ms" }} />

          <div className="hero-grid" style={{ position: "relative", maxWidth: 1200, margin: "0 auto", paddingTop: 88, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(340px, 100%), 1fr))", gap: 56, alignItems: "center" }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 28 }}>
              <div className="in" style={{ ...EYEBROW, animationDelay: "100ms", color: "#fca2ae" }}>Agent evaluation platform</div>
              <h1 className="hero-title" style={{ margin: 0, fontSize: 60, lineHeight: 1.1, letterSpacing: "-0.03em", fontWeight: 300, color: "#ffffff" }}>
                {HEADLINE.map((w, i) => (
                  <span key={`${w.word}-${i}`}>
                    <span
                      className="w"
                      style={{
                        animationDelay: `${w.delay}ms`,
                        ...(w.accent ? { fontWeight: 700, color: "#f8485e", textShadow: "0 0 28px rgba(248,72,94,0.35)" } : {}),
                      }}
                    >
                      {w.word}
                    </span>
                    {i < HEADLINE.length - 1 ? " " : null}
                  </span>
                ))}
              </h1>
              <p className="in" style={{ animationDelay: "900ms", margin: 0, fontSize: 19, lineHeight: 1.6, color: "#efeeee", maxWidth: 540 }}>
                Forge tests, governs and improves your agents on every release. You see how they reason, where they fail and what to fix next.
              </p>
              <div className="in" style={{ animationDelay: "1050ms", display: "flex", gap: 16, flexWrap: "wrap" }}>
                <a className="btn glow" href="#contact" style={{ ...PILL, gap: 10, background: CTA_COLOR, fontWeight: 700 }}>
                  Book a demo
                  <Arrow />
                </a>
                <a className="btn" href="#how" style={{ ...PILL, border: "1px solid rgba(255,255,255,0.5)", fontWeight: 600 }}>
                  See how it works
                </a>
              </div>
            </div>

            {/* Glass scorecard: enters, floats, tilts toward the pointer */}
            <div className="in" style={{ animationDelay: "700ms", animationDuration: "1400ms", perspective: 1200 }}>
              <div className="tilt" style={{ transform: `rotateX(${pointer.rx.toFixed(2)}deg) rotateY(${pointer.ry.toFixed(2)}deg)` }}>
                <div
                  className="float"
                  style={{ position: "relative", background: "rgba(0,0,0,0.70)", border: "1px solid rgba(255,255,255,0.15)", borderRadius: 25, padding: 32, backdropFilter: "blur(16px)", boxShadow: "0 24px 60px rgba(0,0,0,0.45)", display: "flex", flexDirection: "column", gap: 22 }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
                    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                      <div style={{ ...EYEBROW, fontSize: 12, color: "#9a9a97" }}>Evaluation run · illustrative</div>
                      <div style={{ fontSize: 20, fontWeight: 600, color: "#ffffff" }}>ProductAgent · v1.4</div>
                    </div>
                    <div style={{ display: "inline-flex", alignItems: "center", gap: 8, padding: "6px 14px", borderRadius: 12, background: "rgba(90,184,145,0.18)", color: "#8fd6b6", fontSize: 13, fontWeight: 600 }}>
                      <span className="dot" style={{ width: 8, height: 8, borderRadius: 8, background: "#5ab891" }} />
                      Release gate passed
                    </div>
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                    {METRICS.map((m, i) => (
                      <div key={m.label} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 14, fontWeight: 500, color: "#efeeee" }}>
                          <span>{m.label}</span>
                          <span style={{ color: "#ffffff", fontWeight: 600 }}>{m.value}</span>
                        </div>
                        <div style={{ height: 6, borderRadius: 6, background: "rgba(255,255,255,0.12)" }}>
                          <div className="bar" style={{ height: 6, borderRadius: 6, width: `${m.pct}%`, background: m.color, animationDelay: `${1300 + i * 160}ms` }} />
                        </div>
                      </div>
                    ))}
                  </div>
                  <div style={{ paddingTop: 14, borderTop: "1px solid rgba(255,255,255,0.15)", fontSize: 13, color: "#c9c9c6" }}>
                    29 scenarios · 9 regressions caught · reviewed by the release board
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* KINETIC MARQUEE */}
        <section className="mwrap" aria-label="F.O.R.G.E." style={{ overflow: "hidden", background: "#ffffff", padding: "40px 0", borderBottom: "1px solid rgba(60,60,58,0.12)" }}>
          <div className="marquee" aria-hidden="true">
            {marquee.map((w, i) => (
              <div
                key={`${w}-${i}`}
                className="marquee-item"
                style={{ display: "flex", alignItems: "center", gap: 40, paddingRight: 40, fontSize: 64, lineHeight: 1.1, letterSpacing: "-0.03em", fontWeight: 300, color: "#3c3c3a", whiteSpace: "nowrap" }}
              >
                <span>
                  <span style={{ fontWeight: 800, color: "#f8485e" }}>{w.charAt(0)}</span>
                  {w.slice(1)}
                </span>
                <span style={{ width: 12, height: 12, borderRadius: 12, background: "#fca2ae" }} />
              </div>
            ))}
          </div>
        </section>

        {/* F.O.R.G.E. */}
        <section id="framework" style={{ padding: "112px 24px", background: "#ffffff" }}>
          <div style={SECTION_INNER}>
            <div className="rv" style={{ display: "flex", flexDirection: "column", gap: 16, maxWidth: 760 }}>
              <div style={{ ...EYEBROW, color: "#d62e45" }}>The framework</div>
              <h2 className="section-title" style={SECTION_TITLE}>
                Five letters, <span style={{ fontWeight: 700 }}>one discipline</span> for production agents
              </h2>
              <p style={{ margin: 0, fontSize: 18, lineHeight: 1.6, color: "#6b6b68" }}>
                F.O.R.G.E. stands for Framework for Orchestrated Reasoning, Governance &amp; Evaluation. Each part answers a question your risk, product and engineering teams already ask.
              </p>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))", gap: 20 }}>
              {LETTERS.map((l, i) => (
                <div key={l.letter} className={STAGGER[i % 3]}>
                  <div className="lcard lift" style={{ background: "#efeeee", borderRadius: 15, padding: 28, display: "flex", flexDirection: "column", gap: 14, minHeight: 240, height: "100%", boxSizing: "border-box" }}>
                    <div>
                      <span className="big" style={{ fontSize: 64, lineHeight: 1, fontWeight: 800, letterSpacing: "-0.03em", color: "#f8485e" }}>
                        {l.letter}
                      </span>
                    </div>
                    <div style={{ fontSize: 20, fontWeight: 600, color: "#3c3c3a" }}>{l.word}</div>
                    <p style={{ margin: 0, fontSize: 15, lineHeight: 1.6, color: "#3c3c3a" }}>{l.text}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* HOW IT WORKS */}
        <section id="how" style={{ padding: "112px 24px", background: "#efeeee" }}>
          <div style={SECTION_INNER}>
            <div className="rv" style={{ display: "flex", flexDirection: "column", gap: 16, maxWidth: 760 }}>
              <div style={{ ...EYEBROW, color: "#d62e45" }}>How it works</div>
              <h2 className="section-title" style={SECTION_TITLE}>
                A loop that runs on <span style={{ fontWeight: 700 }}>every release</span>
              </h2>
              <p style={{ margin: 0, fontSize: 18, lineHeight: 1.6, color: "#6b6b68" }}>
                Forge plugs into your delivery pipeline. Each change to a prompt, tool or model goes through the same four steps.
              </p>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 28 }}>
              <div aria-hidden="true" style={{ position: "relative", height: 2, background: "rgba(60,60,58,0.12)", borderRadius: 2 }}>
                <div className="line-fill" style={{ position: "absolute", inset: 0, background: "#f8485e", borderRadius: 2, boxShadow: "0 0 12px rgba(248,72,94,0.5)" }} />
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(250px, 1fr))", gap: 20 }}>
                {STEPS.map((s, i) => (
                  <div key={s.num} className={STAGGER[i % 3]}>
                    <div className="lift" style={{ background: "#ffffff", borderRadius: 15, padding: 32, display: "flex", flexDirection: "column", gap: 16, height: "100%", boxSizing: "border-box", boxShadow: "0 2px 8px rgba(60,60,58,0.06), 0 1px 2px rgba(60,60,58,0.04)" }}>
                      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                        <span style={{ fontSize: 14, fontWeight: 700, letterSpacing: "0.05em", color: "#d62e45" }}>{s.num}</span>
                        <span style={{ ...EYEBROW, fontSize: 12, color: "#6b6b68" }}>{s.tag}</span>
                      </div>
                      <h3 style={{ margin: 0, fontSize: 24, lineHeight: 1.3, fontWeight: 600 }}>{s.title}</h3>
                      <p style={{ margin: 0, fontSize: 15, lineHeight: 1.6, color: "#3c3c3a" }}>{s.text}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        {/* CAPABILITIES BENTO */}
        <section id="capabilities" style={{ padding: "112px 24px", background: "#ffffff" }}>
          <div style={SECTION_INNER}>
            <div className="rv" style={{ display: "flex", flexDirection: "column", gap: 16, maxWidth: 760 }}>
              <div style={{ ...EYEBROW, color: "#d62e45" }}>Capabilities</div>
              <h2 className="section-title" style={SECTION_TITLE}>
                Built for teams that ship agents <span style={{ fontWeight: 700 }}>to real users</span>
              </h2>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(320px, 100%), 1fr))", gap: 20 }}>
              <div className="zoomin" style={{ gridRow: "span 2" }}>
                <div className="lift" style={{ position: "relative", overflow: "hidden", height: "100%", boxSizing: "border-box", background: "rgb(46,19,42)", color: "#ffffff", borderRadius: 15, padding: 36, display: "flex", flexDirection: "column", justifyContent: "space-between", gap: 32, minHeight: 420 }}>
                  {/* animated test traces */}
                  <div aria-hidden="true" style={{ position: "relative", height: 170, borderRadius: 12, border: "1px solid rgba(255,255,255,0.15)", overflow: "hidden" }}>
                    <svg width="100%" height="170" viewBox="0 0 320 170" preserveAspectRatio="none" fill="none" aria-hidden="true">
                      <path className="trace" d="M0 40 C60 40 80 90 140 90 S240 30 320 50" stroke="#fca2ae" strokeWidth="1.5" />
                      <path className="trace" d="M0 90 C70 90 90 130 160 120 S250 80 320 100" stroke="#f8485e" strokeWidth="1.5" style={{ animationDuration: "3.4s" }} />
                      <path className="trace" d="M0 140 C80 130 110 70 180 80 S260 140 320 130" stroke="#efeeee" strokeWidth="1" style={{ animationDuration: "4.2s", opacity: 0.6 }} />
                    </svg>
                    <div className="scan" style={{ position: "absolute", left: 0, right: 0, top: 8, height: 2, background: "#ff4d6b", boxShadow: "0 0 18px rgba(248,72,94,0.55), 0 0 44px rgba(248,72,94,0.25)" }} />
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                    <h3 style={{ margin: 0, fontSize: 30, lineHeight: 1.25, fontWeight: 600 }}>Scenario test suites</h3>
                    <p style={{ margin: 0, fontSize: 16, lineHeight: 1.6, color: "#efeeee" }}>
                      Write the conversations your agent must handle, including the awkward ones. Forge replays them against every version and scores each answer on accuracy, tool use and tone.
                    </p>
                  </div>
                </div>
              </div>
              {FEATURES.map((f, i) => (
                <div key={f.title} className={STAGGER[i % 3]}>
                  <div className="lift" style={{ background: "#efeeee", borderRadius: 15, padding: 28, display: "flex", flexDirection: "column", gap: 12, height: "100%", boxSizing: "border-box" }}>
                    <h3 style={{ margin: 0, fontSize: 20, lineHeight: 1.4, fontWeight: 600 }}>{f.title}</h3>
                    <p style={{ margin: 0, fontSize: 15, lineHeight: 1.6, color: "#3c3c3a" }}>{f.text}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* AUDIENCES */}
        <section style={{ padding: "0 24px 112px", background: "#ffffff" }}>
          <div style={{ maxWidth: 1200, margin: "0 auto", display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(300px, 100%), 1fr))", gap: 40, borderTop: "1px solid rgba(60,60,58,0.12)", paddingTop: 72 }}>
            {AUDIENCES.map((a, i) => (
              <div key={a.who} className={STAGGER[i % 3]} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                <div style={{ ...EYEBROW, color: "#6b6b68" }}>{a.who}</div>
                <p style={{ margin: 0, fontSize: 22, lineHeight: 1.4, fontWeight: 500, color: "#3c3c3a" }}>{a.text}</p>
              </div>
            ))}
          </div>
        </section>

        {/* CTA */}
        <section id="contact" style={{ padding: "0 24px 112px", background: "#ffffff" }}>
          <div
            className="zoomin cta-card"
            style={{ position: "relative", overflow: "hidden", maxWidth: 1200, margin: "0 auto", background: "rgb(19,10,30)", borderRadius: 25, padding: "80px 56px", color: "#ffffff", display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 24 }}
          >
            <div aria-hidden="true" className="parallax" style={{ position: "absolute", right: -80, top: 90, width: 640, height: 2 }}>
              <div style={{ position: "absolute", inset: 0, transform: "rotate(-14deg)" }}>
                <div className="breathe" style={NEON} />
                <div className="sweep" style={{ position: "absolute", left: 0, right: 0, top: -1, height: 4, borderRadius: 4, animationDelay: "0.5s" }} />
              </div>
            </div>
            <h2 className="section-title" style={{ position: "relative", margin: 0, fontSize: 48, lineHeight: 1.15, letterSpacing: "-0.02em", fontWeight: 300, maxWidth: 720 }}>
              See how <span style={{ fontWeight: 700 }}>your agents</span> score.
            </h2>
            <p style={{ position: "relative", margin: 0, fontSize: 18, lineHeight: 1.6, color: "#efeeee", maxWidth: 620 }}>
              Bring one agent and a handful of real conversations. In a 45-minute session, our experts run them through Forge and walk you through the results.
            </p>
            <div style={{ position: "relative", display: "flex", gap: 16, flexWrap: "wrap" }}>
              <a className="btn glow" href={DEMO_MAILTO} style={{ ...PILL, gap: 10, background: CTA_COLOR, fontWeight: 700 }}>
                Book a demo
                <Arrow />
              </a>
              <a className="btn" href="#framework" style={{ ...PILL, border: "1px solid rgba(255,255,255,0.5)", fontWeight: 600 }}>
                Read the framework
              </a>
            </div>
          </div>
        </section>
      </main>

      {/* FOOTER */}
      <footer style={{ background: "#efeeee", padding: "48px 24px" }}>
        <div style={{ maxWidth: 1200, margin: "0 auto", display: "flex", justifyContent: "space-between", alignItems: "center", gap: 24, flexWrap: "wrap" }}>
          <Image src="/landing/devoteam-forge.png" alt="Devoteam | Forge" width={170} height={32} style={{ height: 32, width: "auto", display: "block" }} />
          <div style={{ fontSize: 14, color: "#3c3c3a" }}>
            <span style={{ fontWeight: 700, color: "#d62e45" }}>AI-driven tech consulting</span> · Tech for People
          </div>
          <div style={{ display: "flex", gap: 24, fontSize: 14, fontWeight: 500 }}>
            <Link href="/login">Sign in</Link>
            <a href={`mailto:${CONTACT_EMAIL}`}>Contact</a>
          </div>
        </div>
      </footer>
    </div>
  );
}
