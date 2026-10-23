import { UserRound } from "lucide-react";

const colors = ["#E9D8FA", "#CDE9E2", "#F7DABF", "#D7E3FA", "#F6C9D4"];
export default function Avatar({ name, size = 44, active = false }: { name: string; size?: number; active?: boolean }) {
  const hash = [...name].reduce((a, c) => a + c.charCodeAt(0), 0);
  return <span className="avatar-wrap" style={{ width: size, height: size }}>
    <span className="avatar" style={{ background: colors[hash % colors.length], color: "#385452", width: size, height: size, fontSize: size * .34 }}>{name ? name.split(/\s+/).slice(0, 2).map(s => s[0]).join("").toUpperCase() : <UserRound size={size * .5} />}</span>
    {active && <span className="avatar-online" />}
  </span>;
}
