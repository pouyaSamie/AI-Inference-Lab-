import { safeStorage } from "electron";
import { promises as fs } from "node:fs";
import path from "node:path";
import { validateApiBaseUrl } from "./security";

export interface SettingsStatus {
  api_base_url: string;
  token_configured: boolean;
  persistent: boolean;
  storage_backend: string;
  secure_storage_available: boolean;
  note: string;
}

export class SettingsStore {
  private readonly tokenFile: string;
  private readonly secureStorage: boolean;
  private readonly storageBackend: string;
  private apiBaseUrl: string;
  private token: string | null = null;
  private persistent = false;
  private loadNote = "";

  constructor(userDataDir: string) {
    this.tokenFile = path.join(userDataDir, "operator-token.bin");
    this.storageBackend = this.readStorageBackend();
    this.secureStorage = this.storageBackend !== "basic_text" && safeStorage.isEncryptionAvailable();
    const defaultUrl = process.env.LAB_API_URL?.trim() || "http://127.0.0.1:8787";
    const checked = validateApiBaseUrl(defaultUrl);
    this.apiBaseUrl = checked.ok && checked.value ? checked.value : "http://127.0.0.1:8787";
    if (!checked.ok) {
      this.loadNote = `Ignored invalid LAB_API_URL: ${checked.reason ?? "invalid URL"}.`;
    }
    const envToken = process.env.LAB_OPERATOR_TOKEN?.trim();
    if (envToken) {
      this.token = envToken;
      this.loadNote = "Using LAB_OPERATOR_TOKEN from the process environment; it is not persisted by the app.";
    }
  }

  private readStorageBackend(): string {
    try {
      if (typeof safeStorage.getSelectedStorageBackend === "function") {
        return safeStorage.getSelectedStorageBackend();
      }
    } catch {
      return "unavailable";
    }
    return safeStorage.isEncryptionAvailable() ? "encrypted" : "unavailable";
  }

  get baseUrl(): string {
    return this.apiBaseUrl;
  }

  getToken(): string | null {
    return this.token;
  }

  async load(): Promise<void> {
    if (!this.secureStorage || this.token) return;
    try {
      const encrypted = await fs.readFile(this.tokenFile);
      const token = safeStorage.decryptString(encrypted).trim();
      if (token) {
        this.token = token;
        this.persistent = true;
      }
    } catch (error) {
      const code = (error as NodeJS.ErrnoException).code;
      if (code !== "ENOENT") {
        this.loadNote = "The stored operator token could not be decrypted and was not loaded.";
        try {
          await fs.unlink(this.tokenFile);
        } catch {
          // Best-effort cleanup only.
        }
      }
    }
  }

  status(): SettingsStatus {
    const notes: string[] = [];
    if (this.secureStorage) {
      notes.push("Token encryption is available through the operating-system keyring.");
    } else {
      notes.push(
        "No secure OS keyring is available. Tokens stay in Electron main-process memory for this session and are never written in plaintext.",
      );
    }
    if (!this.token) notes.push("No operator token is configured yet.");
    if (this.persistent) notes.push("The operator token is stored encrypted on disk.");
    if (this.loadNote) notes.push(this.loadNote);
    return {
      api_base_url: this.apiBaseUrl,
      token_configured: Boolean(this.token),
      persistent: this.persistent,
      storage_backend: this.storageBackend,
      secure_storage_available: this.secureStorage,
      note: notes.join(" "),
    };
  }

  setApiBaseUrl(raw: string): SettingsStatus {
    const checked = validateApiBaseUrl(raw);
    if (!checked.ok || !checked.value) {
      throw new Error(checked.reason ?? "API URL is invalid");
    }
    this.apiBaseUrl = checked.value;
    this.loadNote = "";
    return this.status();
  }

  async setToken(raw: string): Promise<SettingsStatus> {
    if (typeof raw !== "string") throw new Error("Token must be a string");
    const token = raw.trim();
    if (token.length === 0 || token.length > 4096) throw new Error("Token length is invalid");
    if (/[\u0000-\u001f\u007f]/.test(token)) throw new Error("Token contains control characters");
    this.token = token;
    this.persistent = false;
    this.loadNote = "";
    if (this.secureStorage) {
      const encrypted = safeStorage.encryptString(token);
      const temporary = `${this.tokenFile}.tmp`;
      await fs.mkdir(path.dirname(this.tokenFile), { recursive: true, mode: 0o700 });
      await fs.writeFile(temporary, encrypted, { mode: 0o600 });
      await fs.rename(temporary, this.tokenFile);
      this.persistent = true;
    } else {
      await this.removeTokenFile();
    }
    return this.status();
  }

  async clearToken(): Promise<SettingsStatus> {
    this.token = null;
    this.persistent = false;
    this.loadNote = "";
    await this.removeTokenFile();
    return this.status();
  }

  private async removeTokenFile(): Promise<void> {
    try {
      await fs.unlink(this.tokenFile);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    }
  }
}
