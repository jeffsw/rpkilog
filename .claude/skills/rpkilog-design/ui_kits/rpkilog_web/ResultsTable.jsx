// ResultsTable — main result list with took/shards/hits header.

function StatsLine({ took, shards, hits }) {
  return (
    <div
      style={{
        textAlign: "center",
        color: "var(--rk-fg-dim)",
        fontSize: 12,
        padding: "6px 0",
        letterSpacing: 0,
      }}
    >
      took: {took}ms&nbsp;&nbsp;shards: {shards}&nbsp;&nbsp;hits: {hits.toLocaleString()}
    </div>
  );
}

function ResultsTable({ rows, took, shards, hits }) {
  return (
    <div>
      <StatsLine took={took} shards={shards} hits={hits} />
      <table
        style={{
          borderCollapse: "collapse",
          width: "100%",
          fontSize: 12,
          fontFamily: "var(--rk-font-mono)",
          tableLayout: "auto",
        }}
      >
        <thead>
          <tr>
            <Th>prefix</Th>
            <Th right>maxLength</Th>
            <Th>asn</Th>
            <Th>ta</Th>
            <Th>expires</Th>
            <Th>verb</Th>
            <Th>observation_timestamp</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => <ResultRow key={i} r={r} stripe={i % 2 === 0} />)}
        </tbody>
      </table>
    </div>
  );
}

function Th({ children, right }) {
  return (
    <th
      style={{
        fontWeight: 600,
        textAlign: right ? "right" : "left",
        padding: "3px 10px",
        color: "var(--rk-fg)",
        borderBottom: "1px solid var(--rk-border-dim)",
        whiteSpace: "nowrap",
      }}
    >
      {children}
    </th>
  );
}

function ResultRow({ r, stripe }) {
  const [hover, setHover] = React.useState(false);
  const bg = hover ? "#4a3522" : stripe ? "#3a2a1a" : "transparent";
  return (
    <tr
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{ background: bg }}
    >
      <Td><a className="rk-link" href="#" style={{ color: "var(--rk-amber-500)" }}>{r.prefix}</a></Td>
      <Td right>{r.maxLength}</Td>
      <Td><a className="rk-link" href="#" style={{ color: "var(--rk-amber-500)" }}>{r.asn}</a></Td>
      <Td>{r.ta}</Td>
      <Td>
        <span className="rk-expired" style={{
          color: "var(--rk-fg-dim)",
          textDecoration: "line-through",
          textDecorationColor: "var(--rk-red)",
        }}>
          {r.expires_old}
        </span>
        <br />
        <a className="rk-link" href="#" style={{ color: "var(--rk-amber-500)" }}>{r.expires_new}</a>
      </Td>
      <Td><span className="rk-verb">{r.verb}</span></Td>
      <Td>{r.observation_timestamp}</Td>
    </tr>
  );
}

function Td({ children, right }) {
  return (
    <td
      style={{
        padding: "3px 10px",
        color: "var(--rk-fg)",
        textAlign: right ? "right" : "left",
        whiteSpace: "nowrap",
        verticalAlign: "top",
      }}
    >
      {children}
    </td>
  );
}

Object.assign(window, { ResultsTable, StatsLine });
