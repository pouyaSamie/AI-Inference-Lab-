import { useEffect, useRef, useState } from "react";
import type { LabApi } from "../lib/api";
import type { RecipeView, Schemas } from "../lib/contracts";
import { usePolling } from "../lib/hooks";
import { Badge, ErrorNotice, Notice, Panel } from "./ui";

const terminal = ["completed", "failed", "rejected", "expired", "cancelled"];
type Message = Schemas["ChatMessage"];

export function RecipeSession({ api, view, workerId }: { api: LabApi; view: RecipeView; workerId?: string }) {
  const status = usePolling(() => api.serving(workerId!), 2_000, Boolean(workerId) && !api.demo);
  const session = status.data;
  const [command, setCommand] = useState<Schemas["CommandStatusView"] | null>(null);
  const commands = usePolling(() => api.workerCommands(workerId!), 1_000,
    Boolean(workerId && command && !terminal.includes(command.status)));
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const handled = useRef<string | null>(null);
  const current = commands.data?.find(item => item.command_id === command?.command_id) ??
    (command && terminal.includes(command.status) ? command : undefined);
  const pending = busy || Boolean(command && !terminal.includes(command.status));
  const active = session?.state === "starting" || session?.state === "ready";
  const ready = session?.recipe_id === view.recipe_id && session.state === "ready";

  useEffect(() => {
    if (!current || !terminal.includes(current.status) || handled.current === current.command_id) return;
    handled.current = current.command_id;
    setCommand(current);
    if (current.status !== "completed") {
      setError(Error(current.failure?.message || "The worker could not complete this action. Review engine status and retry."));
    } else if (current.result?.command_type === "RECIPE_CHAT") {
      const content = current.result.content;
      setMessages(history => [...history, { role: "assistant", content }]);
    }
    status.refresh();
  }, [current, status.refresh]);

  const perform = async (action: () => Promise<Schemas["CommandStatusView"]>) => {
    setBusy(true); setError(null);
    try { setCommand(await action()); } catch (caught) { setError(caught); }
    finally { setBusy(false); }
  };

  const send = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!ready || !session || !draft.trim() || pending) return;
    const next: Message[] = [...messages, { role: "user", content: draft.trim() }];
    await perform(async () => {
      const queued = await api.recipeChat(workerId!, { session_id: session.session_id, messages: next, max_tokens: 128 });
      setMessages(next); setDraft(""); return queued;
    });
  };

  return <Panel title="Run this recipe" subtitle="Use the measured settings in Lab chat or another local application.">
    <div className="button-row">
      <Badge tone={ready ? "ok" : "neutral"}>{api.demo ? "Demo — launch unavailable" : session?.state ?? "Engine stopped"}</Badge>
      <button className="button button-primary" disabled={pending || active || !workerId || api.demo || view.status !== "validated" || Boolean(status.error)}
        onClick={() => perform(() => api.runRecipe(view.recipe_id))}>Run recipe</button>
      <button className="button button-danger" disabled={!active || !session || busy}
        onClick={() => perform(() => api.stopRecipe(workerId!, session!.session_id))}>Stop engine</button>
    </div>
    <p>{session?.message ?? "Starting verifies the saved files and uses the GPU. Stop the engine before benchmarking."}</p>
    {session?.state === "starting" && (session.bytes_total ?? 0) > 0 ? <div role="status">
      <progress value={session.bytes_done ?? 0} max={session.bytes_total} aria-label="Recipe file verification" />
      <p>{session.files_done} of {session.files_total} files checked · {Math.min(100,Math.round((session.bytes_done ?? 0) / (session.bytes_total ?? 1) * 100))}%</p>
    </div> : null}
    {command && !terminal.includes(command.status) ? <p role="status">{command.command_type === "RECIPE_CHAT" ? "Generating a reply…" : "Waiting for the worker…"}</p> : null}
    {session?.state === "ready" && session.port ? <label className="field">Local API endpoint
      <input readOnly value={`http://127.0.0.1:${session.port}/v1`} onFocus={event => event.target.select()} />
    </label> : null}
    <p className="muted">The endpoint is local to this computer and has no API key. Minimize keeps it running; Quit stops it. Performance validation does not guarantee answer quality.</p>
    {error || status.error || commands.error ? <ErrorNotice error={error || status.error || commands.error} onRetry={() => {
      if (error && command?.command_type === "RUN_RECIPE" && terminal.includes(command.status) && !active) {
        void perform(() => api.runRecipe(view.recipe_id));
      } else { setError(null); status.refresh(); commands.refresh(); }
    }} /> : null}
    <details><summary>Chat with this model</summary>
      <p className="muted">Messages stay on this computer. Replies are limited to 128 tokens within the recipe context.</p>
      <div aria-live="polite" className="stack">
        {messages.map((message, index) => <div className="notice" key={index}><strong>{message.role === "user" ? "You" : "Model"}</strong><p className="wrap" style={{ whiteSpace: "pre-wrap" }}>{message.content}</p></div>)}
      </div>
      <form onSubmit={send} className="stack">
        <label className="field">Message<textarea value={draft} maxLength={4096} rows={3} onChange={event => setDraft(event.target.value)} disabled={!ready || pending} /></label>
        <div className="button-row"><button className="button button-primary" disabled={!ready || pending || !draft.trim() || messages.length >= 15}>Send</button>
          <button type="button" className="button button-secondary" disabled={pending} onClick={() => { setMessages([]); setError(null); }}>New chat</button></div>
      </form>
      {messages.length >= 15 ? <Notice tone="warn" title="Start a new chat">This conversation reached the message limit.</Notice> : null}
    </details>
  </Panel>;
}
