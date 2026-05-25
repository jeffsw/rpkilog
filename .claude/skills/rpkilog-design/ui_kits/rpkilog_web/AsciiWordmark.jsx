// AsciiWordmark — Figlet-style block-letter rpkilog.com mark.
// Lowercase, always includes the .com.
const ASCII = `            _    _ _                                    
 _ __ _ __ | | _(_) | ___   __ _      ___ ___  _ __ ___  
| '__| '_ \\| |/ / | |/ _ \\ / _\` |    / __/ _ \\| '_ \` _ \\ 
| |  | |_) |   <| | | (_) | (_| | _ | (_| (_) | | | | | |
|_|  | .__/|_|\\_\\_|_|\\___/ \\__, |(_) \\___\\___/|_| |_| |_|
     |_|                   |___/                         `;

function AsciiWordmark({ glow = true }) {
  return (
    <pre
      aria-label="rpkilog.com"
      className={"rk-wordmark" + (glow ? " rk-glow" : "")}
      style={{
        fontFamily: 'ui-monospace,"Courier New",monospace',
        color: "var(--rk-fg)",
        fontSize: 12,
        lineHeight: 1.05,
        margin: 0,
        padding: 0,
        whiteSpace: "pre",
      }}
    >{ASCII}</pre>
  );
}

window.AsciiWordmark = AsciiWordmark;
