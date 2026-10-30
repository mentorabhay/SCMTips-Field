import React from "react";
import Link from "next/link";

export default function NotFound() {
  return (
    <div className="mx-auto flex max-w-xl flex-col items-start gap-3 p-6">
      <h1 className="m-0 text-2xl font-bold">Page not found</h1>
      <p className="m-0 text-muted">This page does not exist in the console.</p>
      <Link href="/" className="font-bold">
        Go to Right now
      </Link>
    </div>
  );
}
