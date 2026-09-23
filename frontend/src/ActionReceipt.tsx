import { useState } from "react";
import type { CommandResult } from "./types";
export function ActionReceipt({ commands }: { commands: CommandResult[] }) {
  const [dismissed, setDismissed] = useState("");
  const c = commands.find((c) =>
    [
      "approve_schedule",
      "approve_placement",
      "approve_access",
      "withdraw_schedule",
    ].includes(c.payload.action),
  );
  if (!c || c.id === dismissed) return null;
  const names: Record<string, string> = {
    approve_schedule: "Equipment booking",
    approve_placement: "Destination change",
    approve_access: "Access work",
    withdraw_schedule: "Booking withdrawal",
  };
  return (
    <div
      className={`action-receipt ${["failed", "rejected"].includes(c.status) ? "failed" : ""}`}
      role="status"
    >
      <div>
        <b>
          {names[c.payload.action]} · {c.status}
        </b>
        <span>
          {c.result?.error ||
            (c.status === "acknowledged"
              ? `Applied at revision ${c.result?.revision}. Physical completion is tracked separately.`
              : "Waiting for the command worker.")}
        </span>
      </div>
      <button
        aria-label="Dismiss action receipt"
        onClick={() => setDismissed(c.id)}
      >
        ×
      </button>
    </div>
  );
}
