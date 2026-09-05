import { useSyncExternalStore } from "react";

let now = Date.now();
let timer: ReturnType<typeof setInterval> | undefined;
const listeners = new Set<() => void>();
function subscribe(listener: () => void) {
  listeners.add(listener);
  if (!timer) {
    now = Date.now();
    timer = setInterval(() => {
      now = Date.now();
      listeners.forEach((notify) => notify());
    }, 1_000);
  }
  return () => {
    listeners.delete(listener);
    if (!listeners.size && timer) {
      clearInterval(timer);
      timer = undefined;
    }
  };
}
export function useLiveClock() {
  return useSyncExternalStore(subscribe, () => now, () => 0);
}

const reducedQuery = "(prefers-reduced-motion: reduce)";
function subscribeMotion(listener: () => void) {
  if (typeof window.matchMedia !== "function") return () => {};
  const query = window.matchMedia(reducedQuery);
  query.addEventListener("change", listener);
  return () => query.removeEventListener("change", listener);
}
export function useReducedMotion() {
  return useSyncExternalStore(
    subscribeMotion,
    () => typeof window.matchMedia === "function" && window.matchMedia(reducedQuery).matches,
    () => true,
  );
}
