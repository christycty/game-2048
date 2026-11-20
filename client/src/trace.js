// Hand-rolled W3C Trace Context for suggest fetches. No browser OTel SDK —
// the server FastAPI instrumentor extracts `traceparent` and continues the trace.

function toHex(bytes) {
    return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

function randomNonZeroHex(byteLength) {
    const bytes = new Uint8Array(byteLength);
    // All-zero ids are invalid in the W3C Trace Context spec.
    do {
        crypto.getRandomValues(bytes);
    } while (bytes.every((b) => b === 0));
    return toHex(bytes);
}

/** @returns {string} `00-{32hex}-{16hex}-01` */
export function createTraceparent() {
    return `00-${randomNonZeroHex(16)}-${randomNonZeroHex(8)}-01`;
}
