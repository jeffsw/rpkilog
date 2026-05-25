// Pagination — flat row of amber page numbers, current is bright green.

function Pagination({ page, pageCount, onChange }) {
  const pages = [];
  for (let i = 0; i < pageCount; i++) pages.push(i);
  return (
    <div style={{
      fontFamily: "var(--rk-font-mono)",
      fontSize: 12,
      color: "var(--rk-fg)",
      marginTop: 10,
    }}>
      <div>Page:</div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "0 8px", marginTop: 2 }}>
        {pages.map(p => (
          <a
            key={p}
            href="#"
            onClick={(e) => { e.preventDefault(); onChange && onChange(p); }}
            style={{
              color: p === page ? "var(--rk-fg-hot)" : "var(--rk-amber-500)",
              textDecoration: p === page ? "none" : "underline",
              fontWeight: p === page ? 700 : 400,
            }}
          >
            {p}
          </a>
        ))}
      </div>
    </div>
  );
}

window.Pagination = Pagination;
