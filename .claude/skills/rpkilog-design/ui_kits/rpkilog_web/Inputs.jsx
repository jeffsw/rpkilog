// Inputs — text input, date-time text-input, button, all in the BBS look.

function TextInput({ value, onChange, placeholder, width, ariaLabel, mono = true, ...rest }) {
  const [focused, setFocused] = React.useState(false);
  return (
    <input
      type="text"
      value={value}
      onChange={(e) => onChange && onChange(e.target.value)}
      onFocus={() => setFocused(true)}
      onBlur={() => setFocused(false)}
      placeholder={placeholder}
      aria-label={ariaLabel}
      spellCheck={false}
      autoComplete="off"
      style={{
        fontFamily: mono ? "var(--rk-font-mono)" : "inherit",
        fontSize: 13,
        color: "var(--rk-fg)",
        background: "#000",
        border: "1px solid " + (focused ? "var(--rk-amber-500)" : "var(--rk-border)"),
        padding: "2px 6px",
        borderRadius: 0,
        outline: "none",
        width: width || 140,
        boxSizing: "border-box",
      }}
      {...rest}
    />
  );
}

function Button({ children, onClick, type = "button", variant = "default", ...rest }) {
  const [hover, setHover] = React.useState(false);
  const [active, setActive] = React.useState(false);
  const isAmber = variant === "amber";
  const baseColor = isAmber ? "var(--rk-amber-500)" : "var(--rk-fg)";
  const bg = hover ? (isAmber ? "var(--rk-amber-500)" : "var(--rk-green-500)") : "#000";
  const fg = hover ? "#000" : baseColor;
  return (
    <button
      type={type}
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => { setHover(false); setActive(false); }}
      onMouseDown={() => setActive(true)}
      onMouseUp={() => setActive(false)}
      style={{
        fontFamily: "var(--rk-font-mono)",
        fontSize: 13,
        fontWeight: 500,
        color: fg,
        background: bg,
        border: "1px solid " + baseColor,
        padding: "2px 14px",
        cursor: "pointer",
        borderRadius: 0,
        boxShadow: active ? "inset 0 0 0 1px " + baseColor : "none",
        transition: "color 0ms, background 0ms",
      }}
      {...rest}
    >
      {children}
    </button>
  );
}

function Label({ children }) {
  return (
    <span style={{ fontSize: 13, color: "var(--rk-fg)", fontFamily: "var(--rk-font-mono)" }}>
      {children}
    </span>
  );
}

Object.assign(window, { TextInput, Button, Label });
