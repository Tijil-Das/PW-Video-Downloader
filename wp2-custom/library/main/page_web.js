import { Util } from "./util.js";

function checkForManifest(body, url) {
    if (!body)
        return;
    const manifest_type = Util.getManifestType(body);
    if (manifest_type) {
        Util.emit("MANIFEST_URL", {
            type: manifest_type,
            url: url,
            tab_url: window.location.href,
            timestamp: new Date().getTime()
        });
    }
}

const xhrBodyExtractors = {
    "": (xhr) => xhr.responseText || xhr.response || null,
    text: (xhr) => xhr.responseText || xhr.response || null,
    json: (xhr) => {
        if (xhr.response == null)
            return null;
        return typeof xhr.response === "string" ? xhr.response : JSON.stringify(xhr.response);
    },
    arraybuffer: (xhr) => Util.decodeArrayBuffer(xhr.response),
    blob: (xhr) => Util.blobToText(xhr.response),
    document: (xhr) =>
        xhr.response?.documentElement
            ? new XMLSerializer().serializeToString(xhr.response)
            : null,
};

async function extractXHRBody(xhr) {
    const extractor = xhrBodyExtractors[xhr.responseType];
    return extractor ? await extractor(xhr) : null;
}

async function extractFetchBody(response) {
    return await response.clone().text();
}

Util.proxy(XMLHttpRequest.prototype, "open", (target, thisArg, args) => {
    const [method, url] = args;
    thisArg.requestMethod = method.toUpperCase();
    thisArg.requestURL = url;
    return target.apply(thisArg, args);
});

Util.proxy(XMLHttpRequest.prototype, "send", (target, thisArg, args) => {
    thisArg.addEventListener("readystatechange", async () => {
        if (thisArg.readyState !== 4)
            return;

        try {
            const body = await extractXHRBody(thisArg);
            checkForManifest(body, thisArg.responseURL);
        } catch (err) {
            console.error("[WVP2]", "XHR manifest extraction failed:", err);
        }
    });

    return target.apply(thisArg, args);
});

Util.proxy(window, "fetch", async (target, thisArg, args) => {
    // this failing causes the exception to show up in the extension logs, but catching the error would make it worse
    const response = await target.apply(thisArg, args);

    try {
        const request = args[0];
        const url = response.url || (typeof request === "string" ? request : request?.url);

        extractFetchBody(response)
            .then((body) => checkForManifest(body, url))
            .catch((err) => console.debug("Fetch manifest extraction failed:", err));
    } catch (err) {
        console.debug("Fetch manifest intercept failed:", err);
    }

    return response;
});