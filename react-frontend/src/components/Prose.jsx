// The briefing is model-written prose over attacker-controlled email bodies, so it is rendered into React
// elements rather than injected as HTML: no innerHTML anywhere on this path.

function inline(text, keyPrefix) {
  // **bold**, *italic*, and `code`; everything else literal.
  const parts = [];
  const pattern = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g;
  let last = 0;
  let match;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) parts.push(text.slice(last, match.index));
    const token = match[0];
    const key = `${keyPrefix}-${match.index}`;
    if (token.startsWith("**")) parts.push(<strong key={key}>{token.slice(2, -2)}</strong>);
    else if (token.startsWith("`")) parts.push(<code key={key}>{token.slice(1, -1)}</code>);
    else parts.push(<em key={key}>{token.slice(1, -1)}</em>);
    last = match.index + token.length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

export default function Prose({ text }) {
  const blocks = [];
  let list = null;

  const flush = () => {
    if (list) {
      blocks.push(
        <ul key={`ul-${blocks.length}`} className="prose-list">
          {list.map((item, index) => <li key={index}>{inline(item, `li-${blocks.length}-${index}`)}</li>)}
        </ul>
      );
      list = null;
    }
  };

  for (const raw of String(text || "").split("\n")) {
    const line = raw.trim();
    if (!line || /^-{3,}$/.test(line)) { flush(); continue; }
    if (/^[-*]\s+/.test(line)) { (list = list || []).push(line.replace(/^[-*]\s+/, "")); continue; }
    flush();
    // A heading is a line that is entirely bold, with or without a leading "#"; the skill's own format also puts a
    // section and its content on one line: "**First thing:** Revise the section."
    const bare = line.replace(/^#+\s*/, "");
    const heading = bare.match(/^\*\*(.+?):?\*\*:?$/);
    const inlineHeading = heading ? null : bare.match(/^\*\*([^*]+?):\*\*:?\s+(.+)$/);
    if (heading || inlineHeading) {
      blocks.push(<h3 key={`h-${blocks.length}`} className="prose-heading">{heading ? heading[1] : inlineHeading[1]}</h3>);
      if (inlineHeading) blocks.push(<p key={`p-${blocks.length}`}>{inline(inlineHeading[2], `p-${blocks.length}`)}</p>);
    } else {
      blocks.push(<p key={`p-${blocks.length}`}>{inline(line, `p-${blocks.length}`)}</p>);
    }
  }
  flush();
  return <div className="prose">{blocks}</div>;
}
