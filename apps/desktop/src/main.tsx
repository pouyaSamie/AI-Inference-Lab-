import { StrictMode, Component, type ErrorInfo, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./styles.css";

class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error): { error: Error } {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // The desktop main process owns logs. Keep renderer details local and bounded.
    console.error("Renderer error", error, info.componentStack);
  }

  render(): ReactNode {
    if (this.state.error) {
      return (
        <div className="empty-state" style={{ minHeight: "100vh" }}>
          <h1>The operator console failed to render</h1>
          <p>{this.state.error.message}</p>
          <p>
            Close and reopen the window. Jobs are owned by the controller and worker; this window never owns or stops a
            running process.
          </p>
          <button className="button button-primary" onClick={() => window.location.reload()}>
            Reload window
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

const root = document.getElementById("root");
if (!root) throw new Error("Missing application root");

createRoot(root).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
);
