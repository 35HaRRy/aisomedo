import { useState } from "react";

export function BrandLogo({ src }: { src?: string | null }) {
  const [failed, setFailed] = useState<string | null>(null);
  const source = src && src !== failed ? src : "/logo.jpg";
  return <img key={source} className="brand-logo" src={source} alt="Logo" width={44} height={44}
    referrerPolicy="no-referrer" onError={() => setFailed(source)} />;
}
