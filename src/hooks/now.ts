import { useState, useEffect } from "react";

export function useNow(refreshInterval?: number): number {
  if (refreshInterval === undefined) {
    refreshInterval = 1000;
  }
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const ivl = setInterval(() => {
      setNow(Date.now());
    }, refreshInterval);
    return () => {
      clearInterval(ivl);
    };
  }, [refreshInterval]);
  return now;
}
