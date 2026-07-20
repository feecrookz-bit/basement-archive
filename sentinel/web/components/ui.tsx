export function Pill({
  tone = "",
  children,
}: {
  tone?: string;
  children: React.ReactNode;
}) {
  return <span className={`pill ${tone}`}>{children}</span>;
}

export function DotPill({ tone, children }: { tone: string; children: React.ReactNode }) {
  return (
    <span className={`pill ${tone}`}>
      <span className="dot" />
      {children}
    </span>
  );
}

export function Section({
  title,
  tone,
  children,
}: {
  title: string;
  tone?: "green" | "amber";
  children: React.ReactNode;
}) {
  return (
    <section className="panel">
      <div className="sect">
        <span className={`ind ${tone === "green" ? "green" : ""}`} />
        <h2>{title}</h2>
      </div>
      {children}
    </section>
  );
}

export function Stat({
  label,
  value,
  tone = "",
}: {
  label: string;
  value: React.ReactNode;
  tone?: "amber" | "green" | "red" | "";
}) {
  return (
    <div className="stat">
      <div className="lbl">{label}</div>
      <div className={`val ${tone}`}>{value}</div>
    </div>
  );
}

export function fmt(n: unknown, digits = 2): string {
  const v = Number(n);
  if (!isFinite(v)) return "—";
  return v.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}
