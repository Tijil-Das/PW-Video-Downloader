export class Util {
    static utf8 = {
        /* Uint8Array -> String */
        decode: b => String.fromCharCode.apply(null, b),
        /* String -> Uint8Array */
        encode: s => Uint8Array.from(s.split("").map(x => x.charCodeAt(0)))
    }

    static b64 = {
        /* b64 String -> Uint8Array */
        decode: s => Uint8Array.from(atob(s), c => c.charCodeAt(0)),
        /* Uint8Array -> b64 String */
        encode: b => btoa(String.fromCharCode(...new Uint8Array(b)))
    };

    static sequenceEquals(arr1, arr2) {
        if (arr1.length !== arr2.length)
            return false;
        return Array.from(arr1).every((value, index) => value === arr2[index]);
    }

    static safeStringify(v) {
        if (v === null)
            return "null";
        if (v === undefined)
            return "undefined";
        if (typeof v === "string")
            return v;

        if (v instanceof ArrayBuffer) {
            return `ArrayBuffer(${v.byteLength})`;
        }
        if (ArrayBuffer.isView(v)) {
            const ctorName = v.constructor.name;
            const length = v instanceof DataView ? v.byteLength : v.length;
            return `${ctorName}(${length})`;
        }
        if (Array.isArray(v)) {
            return `[${v.map(Util.safeStringify).join(", ")}]`;
        }

        try {
            return JSON.stringify(v);
        } catch (e) {
            return String(v);
        }
    }

    static proxy(object, method, handler) {
        const original = object[method];
        if (typeof original !== "function")
            return;

        Object.defineProperty(object, method, {
            value: new Proxy(original, { apply: handler }),
            configurable: true,
            writable: true
        });
    };

    static logEme(eventName, args, func) {
        let err;
        try {
            return func();
        } catch(e) {
            err = e;
            throw e;
        } finally {
            Util.emit(eventName, {
                success: !err,
                args: Util.safeStringify(args)
            });
        }
    }

    static emit(type, data, { timeoutMs = 30000 } = {}) {
        return new Promise((resolve, reject) => {
            const requestId = crypto.randomUUID();

            const timer = timeoutMs
                ? setTimeout(() => {
                    document.removeEventListener('__ext_responseReceived', responseHandler);
                    reject(new Error(`Timed out waiting for response to "${type}" (${requestId})`));
                }, timeoutMs)
                : null;

            const responseHandler = (event) => {
                const { detail } = event;
                if (!detail || detail.requestId !== requestId)
                    return;

                document.removeEventListener('__ext_responseReceived', responseHandler);
                if (timer)
                    clearTimeout(timer);

                if (detail.error) {
                    reject(new Error(detail.error));
                } else {
                    resolve(detail.body);
                }
            };
            document.addEventListener('__ext_responseReceived', responseHandler);

            const requestEvent = new CustomEvent('__ext_response', {
                detail: {
                    type,
                    body: data,
                    requestId,
                }
            });
            document.dispatchEvent(requestEvent);
        });
    }

    static getManifestType(text) {
        const lower = text.toLowerCase();
        if (lower.includes('<mpd') && lower.includes('</mpd>')) {
            return "DASH";
        } else if (lower.includes('#extm3u')) {
            if (lower.includes('#ext-x-stream-inf')) {
                return "HLS_MASTER";
            } else {
                return "HLS_PLAYLIST";
            }
        } else if (lower.includes('<smoothstreamingmedia') && lower.includes('</smoothstreamingmedia>')) {
            return "MSS";
        }
    }

    static decodeArrayBuffer(buffer) {
        if (!buffer || buffer.byteLength === 0)
            return null;

        const arr = new Uint8Array(buffer);
        const decoder = new TextDecoder('utf-8', { fatal: false });

        return arr.length <= 4000
            ? decoder.decode(arr)
            : decoder.decode(arr.slice(0, 2000)) + decoder.decode(arr.slice(-2000));
    }

    static async blobToText(blob) {
        if (!blob)
            return null;

        const isTextLike = blob.type.startsWith('text/') || blob.type.includes('xml') || blob.type.includes('json');

        if (!isTextLike && blob.size >= 2_000_000)
            return null;
        if (blob.size <= 4000)
            return blob.text();

        const head = await blob.slice(0, 2000).text();
        const tail = await blob.slice(-2000).text();
        return head + tail;
    }
}