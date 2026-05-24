// LedePanel — the intro copy block at the top of rpkilog.com.
// Renders the canonical sysadmin-voice paragraphs verbatim.

function LedePanel() {
  return (
    <section className="rk-lede-panel" style={{ marginBottom: 24, maxWidth: 1180 }}>
      <p style={{ margin: "0 0 12px 0", fontSize: 14, lineHeight: 1.5, color: "var(--rk-fg)" }}>
        <strong style={{ fontWeight: 500 }}>rpkilog.com</strong> is available for use, but please consider it a work-in-progress!
        There is an HTTP API but it should not yet be considered stable/supported.
        The source is available on{" "}
        <a className="rk-link" href="https://github.com/jeffsw/rpkilog" target="_blank" rel="noreferrer">
          GitHub: jeffsw/rpkilog
        </a>.
        Please give me a star if this helps you.
      </p>
      <p style={{ margin: "0 0 12px 0", fontSize: 14, lineHeight: 1.5, color: "var(--rk-fg)" }}>
        Thanks to Job Snijders for making his VRP cache snapshots available.
      </p>
      <p style={{ margin: "0 0 12px 0", fontSize: 14, lineHeight: 1.5, color: "var(--rk-fg)" }}>
        This service runs on AWS. If you work there and can help get this project sponsored, please reach out{" "}
        <a className="rk-link" href="mailto:hello@rpkilog.com">by email</a>.
      </p>
      <p style={{ margin: 0, fontSize: 14, lineHeight: 1.5, color: "var(--rk-fg)" }}>Thanks!</p>
    </section>
  );
}

window.LedePanel = LedePanel;
