// SearchFieldset — the RPKI History Search form. Native <fieldset>/<legend>.

function SearchFieldset({ onSearch, initial }) {
  const [prefix, setPrefix] = React.useState(initial?.prefix || "8.8.8.0/24");
  const [asn, setAsn] = React.useState(initial?.asn || "");
  const [from, setFrom] = React.useState(initial?.from || "01 / 01 / 2020 ,  12 : 00 AM");
  const [to, setTo] = React.useState(initial?.to || "01 / 01 / 2038 ,  12 : 00 AM");
  const [perPage, setPerPage] = React.useState(initial?.perPage || "20");

  const submit = (e) => {
    if (e && e.preventDefault) e.preventDefault();
    onSearch && onSearch({ prefix, asn, from, to, perPage: parseInt(perPage, 10) || 20 });
  };

  return (
    <form onSubmit={submit}>
      <fieldset
        style={{
          border: "1px solid var(--rk-border)",
          padding: "6px 14px 10px 14px",
          borderRadius: 0,
          margin: "0 0 6px 0",
        }}
      >
        <legend style={{ padding: "0 6px", color: "var(--rk-fg)", fontSize: 13 }}>
          RPKI History Search
        </legend>
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <Label>Prefix</Label>
          <TextInput value={prefix} onChange={setPrefix} width={130} ariaLabel="prefix" />
          <Label>ASN</Label>
          <TextInput value={asn} onChange={setAsn} width={68} ariaLabel="asn" />
          <Label>Observed Date/Time Range From</Label>
          <TextInput value={from} onChange={setFrom} width={190} ariaLabel="from" />
          <Label>To</Label>
          <TextInput value={to} onChange={setTo} width={190} ariaLabel="to" />
          <Button type="submit" onClick={submit}>Search</Button>
          <Label>Display Entries/Page</Label>
          <TextInput value={perPage} onChange={setPerPage} width={44} ariaLabel="entries per page" />
        </div>
      </fieldset>
    </form>
  );
}

window.SearchFieldset = SearchFieldset;
