import { webcrypto } from "node:crypto";

if (!globalThis.crypto) {
  Object.defineProperty(globalThis, "crypto", { value: webcrypto });
}

if (!window.crypto?.randomUUID) {
  Object.defineProperty(window.crypto, "randomUUID", {
    value: () => webcrypto.randomUUID(),
    configurable: true,
  });
}

(window as typeof window & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
